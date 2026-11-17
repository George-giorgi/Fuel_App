import importlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
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
    _extract_google_vision_total,
    _apply_piusi_total_evidence,
    _apply_piusi_evidence,
    _google_vision_text_detection_disagrees,
    _total_ocr_result,
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
    def test_incomplete_vision_uses_complete_segment_candidate_for_review(self) -> None:
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
        self.assertEqual(result.cumulative_total_suggested_raw_digits, "261563")
        self.assertEqual(result.cumulative_total_litres, 1.663)
        self.assertTrue(any("disagree" in warning for warning in result.warnings))

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
                    expected_digits if vision_digits == expected_digits else None,
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
