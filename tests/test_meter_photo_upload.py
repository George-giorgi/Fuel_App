from hashlib import sha256
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image
from sqlalchemy.orm import Session

from backend.app.api.routers.meter_photos import _meter_photo_read
from backend.app.db.base import Base
from backend.app.db.session import create_database_engine
from backend.app.models import Employee, FuelRecord, GlobalMeterState, Vehicle
from backend.app.schemas.fuel_record import FuelRecordCreate
from backend.app.services.auth import create_employee
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    create_fuel_record,
)
from backend.app.services.meter_ocr import MeterOcrResult
from backend.app.services.meter_photos import (
    InvalidMeterPhoto,
    InvalidQrSession,
    create_vehicle_photo_session,
    recognize_uploaded_meter_photo,
    store_meter_photo,
    validate_meter_photo,
    verify_meter_photo,
)
from backend.app.services.photo_storage import PhotoStorageError
from backend.app.services.vehicles import create_vehicle


class MeterPhotoUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.image = BytesIO()
        Image.new("RGB", (32, 24), color="white").save(
            self.image,
            format="JPEG",
        )
        self.image_bytes = self.image.getvalue()

    def tearDown(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _create_employee_and_vehicle(session: Session) -> tuple[Employee, Vehicle]:
        employee = create_employee(
            session,
            "photo-upload@example.test",
            "Photo Upload",
            "temporary-password",
        )
        vehicle = create_vehicle(session, "UP12 LOD")
        employee.vehicles.append(vehicle)
        session.flush()
        return employee, vehicle

    def _create_photo_session(
        self,
        session: Session,
        employee: Employee,
        vehicle: Vehicle,
    ) -> str:
        created = create_vehicle_photo_session(session, employee, vehicle.id)
        self.assertIsNotNone(created)
        return created[0]

    def test_upload_persists_original_and_same_session_retry_is_idempotent(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            session_token = self._create_photo_session(session, employee, vehicle)
            with (
                patch(
                    "backend.app.services.meter_photos.store_photo",
                    return_value=("original.jpg", None),
                ) as store,
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings"
                ) as extract,
            ):
                first, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    self.image_bytes,
                    "image/jpeg",
                )
                retried, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    self.image_bytes,
                    "image/jpeg",
                )

            self.assertEqual(first.id, retried.id)
            self.assertEqual(first.ocr_status, "pending")
            self.assertEqual(first.sha256, sha256(self.image_bytes).hexdigest())
            store.assert_called_once()
            extract.assert_not_called()

    def test_failed_storage_can_retry_without_consuming_photo_session(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            session_token = self._create_photo_session(session, employee, vehicle)
            with patch(
                "backend.app.services.meter_photos.store_photo",
                side_effect=PhotoStorageError("storage unavailable"),
            ):
                with self.assertRaises(PhotoStorageError):
                    store_meter_photo(
                        session,
                        employee,
                        session_token,
                        self.image_bytes,
                        "image/jpeg",
                    )

            with patch(
                "backend.app.services.meter_photos.store_photo",
                return_value=("original.jpg", None),
            ) as store:
                photo, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    self.image_bytes,
                    "image/jpeg",
                )

            self.assertEqual(photo.ocr_status, "pending")
            store.assert_called_once()

    def test_different_photo_cannot_reuse_an_upload_session(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            session_token = self._create_photo_session(session, employee, vehicle)
            with patch(
                "backend.app.services.meter_photos.store_photo",
                return_value=("original.jpg", None),
            ):
                store_meter_photo(
                    session,
                    employee,
                    session_token,
                    self.image_bytes,
                    "image/jpeg",
                )
                changed_image_buffer = BytesIO()
                Image.new("RGB", (32, 24), color="blue").save(
                    changed_image_buffer,
                    format="JPEG",
                )
                with self.assertRaises(InvalidQrSession):
                    store_meter_photo(
                        session,
                        employee,
                        session_token,
                        changed_image_buffer.getvalue(),
                        "image/jpeg",
                    )

    def test_validation_accepts_multiple_decodable_photo_formats(self) -> None:
        for image_format, expected_extension in (
            ("GIF", ".gif"),
            ("BMP", ".bmp"),
            ("TIFF", ".tiff"),
        ):
            with self.subTest(image_format=image_format):
                image_buffer = BytesIO()
                Image.new("RGB", (32, 24), color="white").save(
                    image_buffer,
                    format=image_format,
                )
                self.assertEqual(
                    validate_meter_photo(
                        image_buffer.getvalue(),
                        "application/octet-stream",
                    ),
                    expected_extension,
                )

    def test_heic_original_is_preserved_and_jpeg_copy_is_used_for_ocr(self) -> None:
        original_heic = b"\x00\x00\x00\x18ftypheic" + bytes(32)
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            session_token = self._create_photo_session(session, employee, vehicle)
            with patch(
                "backend.app.services.meter_photos.store_photo",
                return_value=("original.heic", None),
            ) as store:
                photo, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    original_heic,
                    "image/heic",
                )

            self.assertEqual(photo.storage_key, "original.heic")
            self.assertEqual(photo.sha256, sha256(original_heic).hexdigest())
            store.assert_called_once_with(
                original_heic,
                ".heic",
                "image/heic",
            )
            with (
                patch(
                    "backend.app.services.meter_photos.read_photo",
                    return_value=self.image_bytes,
                ),
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings",
                    return_value=MeterOcrResult(status="uncertain"),
                ) as extract,
            ):
                recognize_uploaded_meter_photo(
                    session,
                    employee,
                    photo.id,
                    self.image_bytes,
                    "image/jpeg",
                )

            extract.assert_called_once_with(self.image_bytes)

        with self.assertRaises(InvalidMeterPhoto):
            validate_meter_photo(b"not an image", "image/heic")

    def test_successful_ocr_retry_reuses_saved_evidence_without_another_call(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            session_token = self._create_photo_session(session, employee, vehicle)
            with patch(
                "backend.app.services.meter_photos.store_photo",
                return_value=("original.jpg", None),
            ):
                photo, registration = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    self.image_bytes,
                    "image/jpeg",
                )

            result = MeterOcrResult(
                status="uncertain",
                provider="google_vision",
                cumulative_total_raw_digits="26798",
                cumulative_total_suggested_raw_digits=None,
                warnings=("The TOTAL row needs manual review.",),
            )
            with (
                patch(
                    "backend.app.services.meter_photos.read_photo",
                    return_value=self.image_bytes,
                ) as read_photo,
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings",
                    return_value=result,
                ) as extract,
            ):
                first = recognize_uploaded_meter_photo(
                    session,
                    employee,
                    photo.id,
                )
                retried = recognize_uploaded_meter_photo(
                    session,
                    employee,
                    photo.id,
                )

            self.assertIs(first, retried)
            self.assertEqual(retried.ocr_status, "uncertain")
            read_photo.assert_called_once_with("original.jpg")
            extract.assert_called_once_with(self.image_bytes)

            fields = _meter_photo_read(
                photo,
                registration,
            ).model_dump(by_alias=True)
            self.assertTrue(fields["ocrRequiresManualReview"])
            self.assertNotIn("ocrCumulativeTotalRawDigits", fields)
            self.assertNotIn("ocrCumulativeTotalSegmentRawDigits", fields)
            self.assertNotIn("ocrWarnings", fields)

    def test_upload_ocr_correction_and_confirmation_preserve_evidence(self) -> None:
        original = self.image_bytes
        with Session(self.engine) as session, session.begin():
            employee, vehicle = self._create_employee_and_vehicle(session)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=261.563,
                    current_total_integer=261_563,
                    current_total_raw_digits="261563",
                    revision=1,
                )
            )
            session.flush()
            session_token = self._create_photo_session(session, employee, vehicle)
            with patch(
                "backend.app.services.meter_photos.store_photo",
                return_value=("original.jpg", None),
            ):
                photo, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    original,
                    "image/jpeg",
                )

            ocr_result = MeterOcrResult(
                status="ready",
                provider="google_vision",
                cumulative_total_litres=261.563,
                cumulative_total_confidence=96,
                cumulative_total_raw_digits="261563",
                cumulative_total_suggested_raw_digits="261563",
            )
            with (
                patch(
                    "backend.app.services.meter_photos.read_photo",
                    return_value=original,
                ),
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings",
                    return_value=ocr_result,
                ),
            ):
                recognize_uploaded_meter_photo(session, employee, photo.id)

            confirmed = verify_meter_photo(
                session,
                employee,
                photo.id,
                cumulative_total_raw_digits="261798",
            )
            self.assertEqual(confirmed.ocr_cumulative_total_raw_digits, "261563")
            self.assertEqual(confirmed.cumulative_total_raw_digits, "261798")
            self.assertTrue(confirmed.cumulative_total_manually_corrected)
            self.assertEqual(confirmed.previous_global_total_integer, 261_563)
            self.assertEqual(confirmed.current_fill_milli_litres, 235)

            record = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meterPhotoId=photo.id,
                    calculatedFillConfirmed=True,
                    odometerMiles=1000,
                ),
            )
            self.assertIsInstance(record, FuelRecord)
            global_meter = session.get(GlobalMeterState, 1)
            self.assertEqual(global_meter.current_total_integer, 261_798)

            with self.assertRaisesRegex(FuelSubmissionError, "already linked"):
                create_fuel_record(
                    session,
                    employee,
                    FuelRecordCreate(
                        meterPhotoId=photo.id,
                        calculatedFillConfirmed=True,
                        odometerMiles=1000,
                    ),
                )
            self.assertEqual(global_meter.current_total_integer, 261_798)
            self.assertEqual(photo.sha256, sha256(original).hexdigest())
