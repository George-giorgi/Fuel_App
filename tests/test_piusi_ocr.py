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
    _apply_piusi_evidence,
    _google_vision_text_detection_disagrees,
    parse_meter_ocr_data,
)
from backend.app.services.piusi_lcd import (
    recognize_piusi_lcd,
)
from backend.app.services import piusi_lcd


DATASET = Path(__file__).parent / "datasets" / "piusi_k600_3"
REFERENCE = DATASET / "reference.jpeg"


def _candidate_ocr_result() -> MeterOcrResult:
    return MeterOcrResult(
        status="ready",
        current_fill_litres=22.032,
        cumulative_total_litres=261563,
        current_fill_confidence=96,
        cumulative_total_confidence=94,
        current_fill_raw_digits="22032",
        current_fill_decimal_position=2,
        cumulative_total_raw_digits="261563",
        cumulative_total_decimal_position=2,
    )


class PiusiOcrTests(unittest.TestCase):
    def test_reference_reads_current_fill_and_whole_cumulative_total(self) -> None:
        labels = json.loads((DATASET / "labels.json").read_text(encoding="utf-8"))
        example = labels["examples"][0]
        result = recognize_piusi_lcd(REFERENCE.read_bytes())

        self.assertTrue(result.display_found)
        self.assertEqual(result.current_fill.raw_digits, "22032")
        self.assertEqual(result.cumulative_total.raw_digits, "261563")
        self.assertIsNone(result.current_fill.decimal_position)
        self.assertIsNone(result.cumulative_total.decimal_position)
        self.assertIsNone(result.current_fill.value)
        self.assertEqual(result.cumulative_total.value, 261563)
        self.assertEqual(
            Decimal(
                f"{example['current_fill_raw_digits'][:example['current_fill_decimal_position']]}."
                f"{example['current_fill_raw_digits'][example['current_fill_decimal_position']:]}"
            ),
            Decimal(example["current_fill"]),
        )
        self.assertEqual(
            Decimal(
                f"{example['cumulative_total_raw_digits'][:example['cumulative_total_decimal_position']]}."
                f"{example['cumulative_total_raw_digits'][example['cumulative_total_decimal_position']:]}"
            ),
            Decimal(example["cumulative_total"]),
        )
        reconciled = _apply_piusi_evidence(
            _candidate_ocr_result(), result, "google_vision"
        )
        self.assertEqual(reconciled.status, "uncertain")
        self.assertEqual(reconciled.cumulative_total_litres, 261563)
        self.assertIn("current-fill decimal point", reconciled.message)
        self.assertNotIn("cumulative-total decimal point", reconciled.message)

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
            result = recognize_piusi_lcd(REFERENCE.read_bytes())

        self.assertEqual(result.cumulative_total.raw_digits, "261563")
        self.assertEqual(result.cumulative_total.value, 261563)

    def test_cumulative_row_uses_all_digits_ignoring_decimal_position(self) -> None:
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
        for decimal_position in (None, 1, 2, 5):
            candidate = replace(
                _candidate_ocr_result(),
                cumulative_total_decimal_position=decimal_position,
            )
            result = _apply_piusi_evidence(candidate, lcd, "google_vision")

            self.assertEqual(result.status, "ready")
            self.assertEqual(result.current_fill_litres, 22.032)
            self.assertEqual(result.cumulative_total_litres, 261563)
            self.assertIsNone(result.cumulative_total_decimal_position)

    def test_cumulative_parser_ignores_decimals_and_preserves_leading_zeros(
        self,
    ) -> None:
        examples = (
            ("26.1563", "261563"),
            ("261563", "261563"),
            ("00.1234", "001234"),
            ("2.61563", "261563"),
            ("2615.63", "261563"),
            ("26.15x63 L", "261563"),
        )
        for text, expected_digits in examples:
            with self.subTest(text=text):
                result = parse_meter_ocr_data(
                    {
                        "text": ["22.032", text],
                        "conf": ["96", "94"],
                        "top": ["100", "140"],
                        "block_num": ["1", "1"],
                        "par_num": ["1", "1"],
                        "line_num": ["1", "2"],
                    }
                )
                self.assertEqual(result.current_fill_litres, 22.032)
                self.assertEqual(result.cumulative_total_litres, int(expected_digits))
                self.assertEqual(result.cumulative_total_raw_digits, expected_digits)
                self.assertIsNone(result.cumulative_total_decimal_position)

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
        conflicting = MeterOcrResult(
            **{
                **_candidate_ocr_result().__dict__,
                "cumulative_total_raw_digits": "261564",
            }
        )

        result = _apply_piusi_evidence(conflicting, lcd, "google_vision")

        self.assertEqual(result.status, "uncertain")
        self.assertTrue(
            any("disagree" in warning for warning in result.warnings)
        )

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

        for impaired in (blurred, low_light, angled, obscured, glare):
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

    def test_missing_current_decimal_requires_manual_review(self) -> None:
        lcd = recognize_piusi_lcd(REFERENCE.read_bytes())
        result = _apply_piusi_evidence(
            MeterOcrResult(
                status="ready",
                current_fill_litres=22032.0,
                cumulative_total_litres=261563,
                current_fill_confidence=96,
                cumulative_total_confidence=94,
                current_fill_raw_digits="22032",
                cumulative_total_raw_digits="261563",
            ),
            lcd,
            "google_vision",
        )

        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.current_fill_litres)
        self.assertEqual(result.cumulative_total_litres, 261563)

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


if __name__ == "__main__":
    unittest.main()
