import importlib
import json
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from backend.app.services.meter_ocr import (
    MeterOcrResult,
    _extract_tesseract_total,
    _extract_google_vision_total,
    _apply_piusi_total_evidence,
    _apply_piusi_evidence,
    _google_vision_text_detection_disagrees,
    _total_ocr_result,
    extract_meter_readings,
    parse_meter_ocr_data,
)
from backend.app.services.piusi_lcd import (
    recognize_piusi_lcd,
    recognize_piusi_total,
)
from backend.app.services import piusi_lcd


DATASET = Path(__file__).parent / "datasets" / "piusi_k600_3"
REFERENCE = DATASET / "reference.jpeg"


def _candidate_ocr_result() -> MeterOcrResult:
    return MeterOcrResult(
        status="ready",
        current_fill_litres=22032,
        cumulative_total_litres=261.563,
        current_fill_confidence=96,
        cumulative_total_confidence=94,
        current_fill_raw_digits="22032",
        cumulative_total_raw_digits="261563",
    )


class PiusiOcrTests(unittest.TestCase):
    def test_incomplete_vision_does_not_promote_a_conflicting_segment_candidate(
        self,
    ) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        result = _apply_piusi_total_evidence(
            MeterOcrResult(
                status="uncertain",
                cumulative_total_litres=1.663,
                cumulative_total_confidence=60,
                cumulative_total_raw_digits="1663",
            ),
            lcd,
            "google_vision",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.cumulative_total_raw_digits, "1663")
        self.assertEqual(result.cumulative_total_segment_raw_digits, "261563")
        self.assertIsNone(result.cumulative_total_suggested_raw_digits)
        self.assertEqual(result.cumulative_total_litres, 1.663)
        self.assertTrue(any("disagree" in warning for warning in result.warnings))

    def test_opencv_candidate_is_not_suggested_without_ocr_digits(self) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        result = _apply_piusi_total_evidence(
            MeterOcrResult(status="uncertain"),
            lcd,
            "tesseract",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.cumulative_total_raw_digits)
        self.assertEqual(result.cumulative_total_segment_raw_digits, "261563")
        self.assertIsNone(result.cumulative_total_suggested_raw_digits)
        self.assertTrue(
            any(
                "Tesseract did not return TOTAL digits" in warning
                for warning in result.warnings
            )
        )

    def test_complete_conflicting_candidates_require_manual_digits(self) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        result = _apply_piusi_total_evidence(
            MeterOcrResult(
                status="uncertain",
                cumulative_total_litres=267.981,
                cumulative_total_confidence=67,
                cumulative_total_raw_digits="267981",
            ),
            lcd,
            "google_vision",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.cumulative_total_raw_digits, "267981")
        self.assertEqual(result.cumulative_total_segment_raw_digits, "261563")
        self.assertIsNone(result.cumulative_total_suggested_raw_digits)
        self.assertTrue(any("disagree" in warning for warning in result.warnings))

    def test_ocr_candidate_requires_exactly_six_digits(self) -> None:
        for digits in ("26156", "2615630"):
            with self.subTest(digits=digits):
                result = _total_ocr_result(digits, 96, "google_vision")
                self.assertEqual(result.status, "uncertain")
                self.assertEqual(result.cumulative_total_raw_digits, digits)
                self.assertTrue(
                    any("exactly six digits" in warning for warning in result.warnings)
                )

    def test_total_ocr_does_not_convert_ambiguous_letters_to_digits(self) -> None:
        result = _total_ocr_result("26I563", 96, "google_vision")

        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.cumulative_total_raw_digits, "26563")
        self.assertTrue(
            any("exactly six digits" in warning for warning in result.warnings)
        )

    def test_tesseract_reads_tight_bottom_digits_and_threshold_variants(self) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        tesseract_result = {"text": ["261563"], "conf": ["96"]}
        with patch(
            "pytesseract.image_to_data",
            return_value=tesseract_result,
        ) as image_to_data:
            result = _extract_tesseract_total(lcd)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertEqual(image_to_data.call_count, 6)
        with Image.open(BytesIO(lcd.display_crop)) as display:
            full_display_height = round(display.height * 1600 / display.width)
        self.assertTrue(
            all(
                call.args[0].height < full_display_height
                for call in image_to_data.call_args_list
            )
        )

    def test_tesseract_disagreeing_bottom_row_variants_require_review(self) -> None:
        outputs = [
            {"text": ["261563"], "conf": ["96"]},
            {"text": ["261563"], "conf": ["95"]},
            {"text": ["261563"], "conf": ["94"]},
            {"text": ["261798"], "conf": ["96"]},
            {"text": ["261798"], "conf": ["95"]},
            {"text": ["261798"], "conf": ["94"]},
        ]
        with patch(
            "pytesseract.image_to_data", side_effect=outputs
        ) as image_to_data:
            result = _extract_tesseract_total(
                recognize_piusi_total(REFERENCE.read_bytes())
            )

        self.assertEqual(result.status, "uncertain")
        self.assertEqual(image_to_data.call_count, 6)
        self.assertTrue(
            any("preprocessing variants disagree" in warning for warning in result.warnings)
        )
        self.assertEqual(
            result.cumulative_total_raw_digits,
            "261563",
        )

    def test_tesseract_falls_back_to_lower_row_when_digit_crop_is_unreadable(
        self,
    ) -> None:
        outputs = [
            {},
            {},
            {},
            {"text": ["261563"], "conf": ["96"]},
            {"text": ["261563"], "conf": ["95"]},
            {"text": ["261563"], "conf": ["94"]},
        ]
        with patch(
            "pytesseract.image_to_data",
            side_effect=outputs,
        ) as image_to_data:
            result = _extract_tesseract_total(
                recognize_piusi_total(REFERENCE.read_bytes())
            )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertEqual(image_to_data.call_count, 6)

    def test_tesseract_unreadable_message_names_selected_provider(self) -> None:
        result = _total_ocr_result("", 0, "tesseract")

        self.assertIn("Tesseract could not read", result.message)

    def test_tesseract_executable_failure_is_reported(self) -> None:
        with patch(
            "pytesseract.image_to_data",
            side_effect=subprocess.CalledProcessError(6, "tesseract --version"),
        ):
            result = _extract_tesseract_total(
                recognize_piusi_total(REFERENCE.read_bytes())
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("Tesseract executable failed", result.message)

    def test_meter_extraction_uses_only_total_row_recognition(self) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        with (
            patch.dict(
                "os.environ",
                {
                    "FUEL_OCR_PROVIDER": "google_vision",
                    "GOOGLE_CLOUD_VISION_API_KEY": "test-key",
                },
                clear=True,
            ),
            patch(
                "backend.app.services.meter_ocr.recognize_piusi_total",
                return_value=lcd,
            ) as recognize_total,
            patch(
                "backend.app.services.meter_ocr.recognize_piusi_lcd",
                side_effect=AssertionError("top-row OCR must not run"),
            ),
            patch(
                "backend.app.services.meter_ocr._extract_google_vision_total",
                return_value=MeterOcrResult(status="uncertain"),
            ),
        ):
            extract_meter_readings(REFERENCE.read_bytes())

        recognize_total.assert_called_once()

    def test_google_vision_uses_only_the_detected_total_row_crop(self) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        response_data = {"responses": [{}]}
        with (
            patch(
                "backend.app.services.meter_ocr._prepare_google_vision_detected_image",
                return_value=b"prepared-total-row",
            ) as prepare_image,
            patch(
                "backend.app.services.meter_ocr._call_google_vision",
                return_value=response_data,
            ) as call_vision,
            patch(
                "backend.app.services.meter_ocr._google_vision_response_lines",
                return_value=[(0, "261563", 96)],
            ),
        ):
            result = _extract_google_vision_total("test-key", lcd)

        prepare_image.assert_called_once_with(
            lcd.total_row_crop,
            grayscale=True,
            min_width=1600,
        )
        call_vision.assert_called_once_with(
            [b"prepared-total-row"],
            "test-key",
            text_detection_first=True,
        )
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertEqual(result.status, "ready")

    def test_conflicting_google_vision_sequences_are_preserved_as_uncertain(
        self,
    ) -> None:
        lcd = recognize_piusi_total(REFERENCE.read_bytes())
        with (
            patch(
                "backend.app.services.meter_ocr._prepare_google_vision_detected_image",
                return_value=b"prepared-total-row",
            ),
            patch(
                "backend.app.services.meter_ocr._call_google_vision",
                return_value={"responses": [{}]},
            ),
            patch(
                "backend.app.services.meter_ocr._google_vision_response_lines",
                return_value=[
                    (0, "261563", 96),
                    (1, "267981", 92),
                ],
            ),
        ):
            result = _extract_google_vision_total("test-key", lcd)

        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertTrue(any("261563, 267981" in warning for warning in result.warnings))

    def test_total_segment_classifier_rejects_extra_digits(self) -> None:
        display = np.zeros((100, 450, 3), dtype=np.uint8)
        boxes = [
            (10 + index * 55, 20, 20, 60)
            for index in range(7)
        ]

        with (
            patch.object(piusi_lcd, "_group_components", return_value=boxes),
            patch.object(
                piusi_lcd, "_classify_glyph", return_value=("1", 0.9)
            ),
        ):
            result = piusi_lcd._recognize_row(
                display,
                (0, 0, 1, 1),
                minimum_digits=6,
                split_wide_glyphs=True,
                segment_threshold=0.45,
                whole_number=True,
                expected_digits=6,
                adaptive_masks=False,
                minimum_agreeing_masks=1,
            )

        self.assertIsNone(result.raw_digits)

    def test_total_row_preserves_repeated_digits_and_leading_zeros(self) -> None:
        segment_regions = {
            "a": (0.25, 0.03, 0.75, 0.22),
            "b": (0.67, 0.14, 0.95, 0.46),
            "c": (0.67, 0.54, 0.95, 0.86),
            "d": (0.25, 0.78, 0.75, 0.97),
            "e": (0.05, 0.54, 0.33, 0.86),
            "f": (0.05, 0.14, 0.33, 0.46),
            "g": (0.25, 0.42, 0.75, 0.60),
        }
        segments_by_digit = {
            "0": "abcdef",
            "1": "bc",
            "2": "abged",
            "3": "abgcd",
            "4": "fgbc",
            "5": "afgcd",
            "6": "afgecd",
            "7": "abc",
            "8": "abcdefg",
            "9": "abfgcd",
        }

        for expected in ("000125", "111111", "270001", "261798"):
            with self.subTest(expected=expected):
                glyph_width = 100
                glyph_gap = 30
                row_height = 160
                row_width = 24 + len(expected) * glyph_width + 5 * glyph_gap
                display = np.full(
                    (row_height, row_width, 3),
                    (120, 185, 125),
                    dtype=np.uint8,
                )
                for index, digit in enumerate(expected):
                    x = 12 + index * (glyph_width + glyph_gap)
                    for segment in segments_by_digit[digit]:
                        left, top, right, bottom = segment_regions[segment]
                        cv2.rectangle(
                            display,
                            (
                                x + round(left * glyph_width),
                                10 + round(top * 140),
                            ),
                            (
                                x + round(right * glyph_width),
                                10 + round(bottom * 140),
                            ),
                            (190, 40, 20),
                            thickness=-1,
                        )

                result = piusi_lcd._recognize_row(
                    display,
                    (0, 0, 1, 1),
                    minimum_digits=6,
                    split_wide_glyphs=True,
                    segment_threshold=0.45,
                    whole_number=True,
                    expected_digits=6,
                    adaptive_masks=False,
                    minimum_agreeing_masks=1,
                )

                self.assertEqual(result.raw_digits, expected)

    def test_low_light_crop_fallback_recognizes_labeled_total(self) -> None:
        image = (DATASET / "example_dark_60313_261798.jpeg").read_bytes()
        original_candidate = piusi_lcd._lcd_candidate

        def low_light_only(
            source: np.ndarray,
            *,
            saturation_floor: int = 35,
            value_floor: int = 140,
        ) -> np.ndarray | None:
            if value_floor != 110:
                return None
            return original_candidate(
                source,
                saturation_floor=saturation_floor,
                value_floor=value_floor,
            )

        with patch.object(
            piusi_lcd,
            "_lcd_candidate",
            side_effect=low_light_only,
        ):
            result = recognize_piusi_total(image)

        self.assertEqual(result.cumulative_total.raw_digits, "261798")
        self.assertEqual(len(result.cumulative_total.raw_digits), 6)
        self.assertTrue(result.total_row_crop)

    def test_current_fill_rejects_a_truncated_three_digit_reading(self) -> None:
        display = np.zeros((100, 200, 3), dtype=np.uint8)
        boxes = [
            (20, 20, 20, 60),
            (70, 20, 20, 60),
            (120, 20, 20, 60),
        ]

        with (
            patch.object(piusi_lcd, "_group_components", return_value=boxes),
            patch.object(
                piusi_lcd, "_classify_glyph", return_value=("0", 0.9)
            ),
        ):
            result = piusi_lcd._recognize_row(
                display,
                (0, 0, 1, 1),
                minimum_digits=3,
                split_wide_glyphs=False,
                segment_threshold=0.35,
                whole_number=True,
                expected_digits=5,
                adaptive_masks=False,
                minimum_agreeing_masks=1,
            )

        self.assertIsNone(result.raw_digits)

    def test_current_fill_accepts_a_different_digit_count(self) -> None:
        display = np.zeros((100, 350, 3), dtype=np.uint8)
        boxes = [
            (20 + index * 50, 20, 20, 60)
            for index in range(6)
        ]

        with (
            patch.object(piusi_lcd, "_group_components", return_value=boxes),
            patch.object(
                piusi_lcd, "_classify_glyph", return_value=("1", 0.9)
            ),
        ):
            result = piusi_lcd._recognize_row(
                display,
                (0, 0, 1, 1),
                minimum_digits=3,
                split_wide_glyphs=False,
                segment_threshold=0.35,
                whole_number=True,
                adaptive_masks=False,
                minimum_agreeing_masks=1,
            )

        self.assertEqual(result.raw_digits, "111111")
        self.assertEqual(result.value, Decimal("111.111"))

    def test_reference_reads_exactly_six_total_digits(self) -> None:
        labels = json.loads((DATASET / "labels.json").read_text(encoding="utf-8"))
        example = labels["examples"][0]
        result = recognize_piusi_total(REFERENCE.read_bytes())

        self.assertTrue(result.display_found)
        self.assertEqual(result.cumulative_total.raw_digits, "261563")
        self.assertEqual(result.cumulative_total.decimal_position, 3)
        self.assertEqual(result.cumulative_total.value, Decimal("261.563"))
        self.assertEqual(example["cumulative_total_decimal_position"], 3)
        self.assertEqual(
            int(example["cumulative_total_raw_digits"]),
            int(Decimal(example["cumulative_total"]) * 1000),
        )
        reconciled = _apply_piusi_total_evidence(
            MeterOcrResult(
                status="ready",
                cumulative_total_litres=261.563,
                cumulative_total_confidence=94,
                cumulative_total_raw_digits="261563",
            ),
            result,
            "google_vision",
        )
        self.assertEqual(reconciled.status, "ready")
        self.assertEqual(reconciled.cumulative_total_litres, 261.563)
        self.assertEqual(reconciled.cumulative_total_suggested_raw_digits, "261563")

    def test_total_row_crop_keeps_the_complete_vision_area(self) -> None:
        result = recognize_piusi_total(REFERENCE.read_bytes())
        display = cv2.imdecode(
            np.frombuffer(result.display_crop, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        total_row = cv2.imdecode(
            np.frombuffer(result.total_row_crop, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        height, width = display.shape[:2]

        self.assertEqual(
            total_row.shape[1],
            round(width * 0.82) - round(width * 0.10),
        )
        self.assertEqual(
            total_row.shape[0],
            round(height * 0.96) - round(height * 0.58),
        )

    def test_large_photo_is_bounded_for_ocr_without_changing_labeled_digits(self) -> None:
        image_buffer = BytesIO()
        with Image.open(REFERENCE) as image:
            image.resize(
                (image.width * 3, image.height * 3),
                Image.Resampling.LANCZOS,
            ).save(image_buffer, format="JPEG", quality=95)

        result = recognize_piusi_total(image_buffer.getvalue())

        self.assertEqual(result.cumulative_total.raw_digits, "261563")

    def test_labeled_lcd_crops_match_digits_and_review_status(self) -> None:
        labels = json.loads((DATASET / "labels.json").read_text(encoding="utf-8"))
        for example in labels["examples"][1:]:
            with self.subTest(image=example["image"]):
                result = recognize_piusi_total(
                    (DATASET / example["image"]).read_bytes()
                )
                self.assertTrue(result.display_found)
                expected_digits = example["cumulative_total_raw_digits"]
                self.assertEqual(result.cumulative_total.raw_digits, expected_digits)
                self.assertEqual(
                    result.cumulative_total.decimal_position, 3
                )
                self.assertEqual(
                    result.cumulative_total.value,
                    Decimal(example["cumulative_total"]),
                )
                vision_digits = example.get(
                    "google_vision_raw_digits", expected_digits
                )
                vision_result = MeterOcrResult(
                    status="ready",
                    cumulative_total_litres=float(Decimal(vision_digits).scaleb(-3)),
                    cumulative_total_confidence=67 if vision_digits != expected_digits else 94,
                    cumulative_total_raw_digits=vision_digits,
                    cumulative_total_decimal_position=3,
                )
                reconciled = _apply_piusi_total_evidence(
                    vision_result, result, "google_vision"
                )
                self.assertEqual(
                    reconciled.status, example["expected_ocr_status"]
                )
                self.assertEqual(reconciled.cumulative_total_raw_digits, vision_digits)
                self.assertEqual(
                    reconciled.cumulative_total_segment_raw_digits, expected_digits
                )
                self.assertEqual(
                    reconciled.cumulative_total_suggested_raw_digits,
                    (
                        vision_digits
                        if (
                            vision_digits == expected_digits
                            and example["expected_ocr_status"] == "ready"
                        )
                        else None
                    ),
                )

    def test_cumulative_row_uses_adaptive_threshold_when_color_is_absent(self) -> None:
        image = piusi_lcd._load_oriented_image(REFERENCE.read_bytes())
        display = piusi_lcd._lcd_candidate(image)
        self.assertIsNotNone(display)
        assert display is not None
        height, width = display.shape[:2]
        top, bottom = round(height * 0.65), round(height * 0.96)
        left, right = round(width * 0.15), round(width * 0.95)
        row = display[top:bottom, left:right]
        gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
        display[top:bottom, left:right] = cv2.cvtColor(
            gray, cv2.COLOR_GRAY2BGR
        )

        with patch.object(piusi_lcd, "_lcd_candidate", return_value=display):
            result = recognize_piusi_total(REFERENCE.read_bytes())

        self.assertEqual(result.cumulative_total.raw_digits, "261563")
        self.assertEqual(result.cumulative_total.value, Decimal("261.563"))

    def test_both_rows_use_all_digits_ignoring_decimal_position(self) -> None:
        lcd = recognize_piusi_lcd(REFERENCE.read_bytes())
        lcd = replace(
            lcd,
            current_fill=replace(
                lcd.current_fill,
                decimal_position=2,
                value=Decimal("22.032"),
            ),
            warnings=(),
        )
        for current_decimal_position in (None, 1, 2, 5):
            for total_decimal_position in (None, 1, 2, 5):
                candidate = replace(
                    _candidate_ocr_result(),
                    current_fill_decimal_position=current_decimal_position,
                    cumulative_total_decimal_position=total_decimal_position,
                )
                result = _apply_piusi_evidence(candidate, lcd, "google_vision")

                self.assertEqual(result.status, "ready")
                self.assertEqual(result.current_fill_litres, 22032)
                self.assertEqual(result.cumulative_total_litres, 261.563)
                self.assertEqual(result.current_fill_decimal_position, 2)
                self.assertEqual(result.cumulative_total_decimal_position, 3)

    def test_parser_ignores_decimals_for_both_rows_and_preserves_leading_zeros(
        self,
    ) -> None:
        current_examples = ("22.032", "22032", "2.2032")
        examples = (
            ("26.1563", "261563"),
            ("261563", "261563"),
            ("00.1234", "001234"),
            ("2.61563", "261563"),
            ("2615.63", "261563"),
            ("26.15x63 L", "261563"),
        )
        for current_text in current_examples:
            for text, expected_digits in examples:
                with self.subTest(current_text=current_text, total_text=text):
                    result = parse_meter_ocr_data(
                        {
                            "text": [current_text, text],
                            "conf": ["96", "94"],
                            "top": ["100", "140"],
                            "block_num": ["1", "1"],
                            "par_num": ["1", "1"],
                            "line_num": ["1", "2"],
                        }
                    )
                    self.assertEqual(result.current_fill_litres, 22032)
                    self.assertEqual(result.current_fill_raw_digits, "22032")
                    self.assertEqual(result.current_fill_decimal_position, 2)
                    self.assertEqual(
                        result.cumulative_total_litres,
                        int(expected_digits) / 1000,
                    )
                    self.assertEqual(
                        result.cumulative_total_raw_digits,
                        expected_digits,
                    )
                    self.assertEqual(
                        result.cumulative_total_decimal_position,
                        max(0, len(expected_digits) - 3),
                    )

    def test_missing_cumulative_digit_requires_manual_review(self) -> None:
        lcd = recognize_piusi_lcd(REFERENCE.read_bytes())
        result = _apply_piusi_evidence(
            replace(
                _candidate_ocr_result(),
                cumulative_total_raw_digits="26163",
            ),
            lcd,
            "google_vision",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertIn("cumulative-total digits need manual review", result.message)

    def test_blurry_cumulative_digits_require_manual_review(self) -> None:
        original = cv2.imread(str(REFERENCE))
        blurred = cv2.GaussianBlur(original, (31, 31), 0)
        success, encoded = cv2.imencode(".jpg", blurred)
        self.assertTrue(success)

        lcd = recognize_piusi_lcd(encoded.tobytes())
        result = _apply_piusi_evidence(
            _candidate_ocr_result(),
            lcd,
            "google_vision",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertTrue(
            result.cumulative_total_litres is None
            or any("cumulative-total" in warning for warning in result.warnings)
        )

    def test_vision_segment_disagreement_requires_manual_review(self) -> None:
        lcd = recognize_piusi_lcd(REFERENCE.read_bytes())
        conflicting = replace(
            _candidate_ocr_result(),
            cumulative_total_litres=92.951,
            cumulative_total_raw_digits="92951",
        )

        result = _apply_piusi_evidence(conflicting, lcd, "google_vision")

        self.assertEqual(result.status, "uncertain")
        self.assertTrue(
            any("disagree" in warning for warning in result.warnings)
        )
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertEqual(result.cumulative_total_litres, 261.563)

    def test_text_and_document_detection_disagreement_is_detected(self) -> None:
        response = {
            "textAnnotations": [{"description": "22.032 26.1563"}]
        }
        document = {"text": "22.032 26.1568"}

        self.assertTrue(
            _google_vision_text_detection_disagrees(response, document)
        )
        self.assertFalse(
            _google_vision_text_detection_disagrees(
                {"textAnnotations": [{"description": "22.032"}]},
                {"text": "22.032"},
            )
        )

    def test_unreadable_or_impaired_photos_never_become_ready_automatically(self) -> None:
        original = cv2.imread(str(REFERENCE))
        height, width = original.shape[:2]
        blurred = cv2.GaussianBlur(original, (31, 31), 0)
        low_light = np.clip(original.astype(np.float32) * 0.35, 0, 255).astype(
            np.uint8
        )
        rotation = cv2.getRotationMatrix2D((width / 2, height / 2), 12, 1)
        angled = cv2.warpAffine(original, rotation, (width, height))
        obscured = original.copy()
        cv2.rectangle(obscured, (275, 485), (325, 555), (20, 20, 20), -1)
        glare_image = Image.fromarray(cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(glare_image, "RGBA")
        draw.ellipse((250, 450, 365, 550), fill=(255, 255, 255, 180))
        glare = cv2.cvtColor(np.asarray(glare_image.convert("RGB")), cv2.COLOR_RGB2BGR)

        success, encoded = cv2.imencode(".jpg", angled)
        self.assertTrue(success)
        angled_lcd = recognize_piusi_lcd(encoded.tobytes())
        self.assertEqual(angled_lcd.current_fill.raw_digits, "22032")
        self.assertEqual(angled_lcd.cumulative_total.raw_digits, "261563")

        for impaired in (blurred, low_light, obscured, glare):
            success, encoded = cv2.imencode(".jpg", impaired)
            self.assertTrue(success)
            lcd = recognize_piusi_lcd(encoded.tobytes())
            result = _apply_piusi_evidence(
                _candidate_ocr_result(), lcd, "google_vision"
            )
            self.assertNotEqual(result.status, "ready")

    def test_missing_display_is_not_accepted(self) -> None:
        blank = np.full((600, 800, 3), 255, dtype=np.uint8)
        success, encoded = cv2.imencode(".jpg", blank)
        self.assertTrue(success)

        lcd = recognize_piusi_lcd(encoded.tobytes())
        result = _apply_piusi_evidence(
            _candidate_ocr_result(), lcd, "google_vision"
        )

        self.assertFalse(lcd.display_found)
        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.current_fill_litres)
        self.assertIsNone(result.cumulative_total_litres)

    def test_fixed_three_decimal_positions_are_applied_to_both_rows(self) -> None:
        lcd = recognize_piusi_lcd(REFERENCE.read_bytes())
        result = _apply_piusi_evidence(
            _candidate_ocr_result(), lcd, "google_vision"
        )

        self.assertEqual(result.current_fill_litres, 22032)
        self.assertEqual(result.current_fill_decimal_position, 2)
        self.assertEqual(result.cumulative_total_litres, 261.563)
        self.assertEqual(result.cumulative_total_decimal_position, 3)

    def test_metadata_migration_is_additive_on_sqlite(self) -> None:
        migration = importlib.import_module(
            "backend.migrations.versions.0015_piusi_ocr_evidence"
        )
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE meter_photos (id INTEGER PRIMARY KEY)"
                )
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()
                columns = {
                    column["name"]
                    for column in inspect(connection).get_columns("meter_photos")
                }
                self.assertTrue(
                    {
                        "ocr_provider",
                        "ocr_current_fill_raw_digits",
                        "ocr_current_fill_decimal_position",
                        "ocr_cumulative_total_raw_digits",
                        "ocr_cumulative_total_decimal_position",
                        "ocr_current_fill_segment_confidence",
                        "ocr_cumulative_total_segment_confidence",
                        "ocr_warnings",
                    }.issubset(columns)
                )
                with Operations.context(context):
                    migration.downgrade()
                self.assertEqual(
                    {column["name"] for column in inspect(connection).get_columns(
                        "meter_photos"
                    )},
                    {"id"},
                )
        finally:
            engine.dispose()

    def test_total_candidate_migration_is_additive_on_sqlite(self) -> None:
        migration = importlib.import_module(
            "backend.migrations.versions.0020_piusi_candidate_evidence"
        )
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE meter_photos (id INTEGER PRIMARY KEY)"
                )
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()
                columns = {
                    column["name"]
                    for column in inspect(connection).get_columns("meter_photos")
                }
                self.assertTrue(
                    {
                        "ocr_cumulative_total_segment_raw_digits",
                        "suggested_cumulative_total_raw_digits",
                    }.issubset(columns)
                )
                with Operations.context(context):
                    migration.downgrade()
                self.assertEqual(
                    {column["name"] for column in inspect(connection).get_columns(
                        "meter_photos"
                    )},
                    {"id"},
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
