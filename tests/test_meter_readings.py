from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import unittest

from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.session import create_database_engine
from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterState,
    MeterPhoto,
    MeterReadingReview,
    QrSession,
    Vehicle,
)
from backend.app.schemas.fuel_record import (
    FuelRecordCreate,
    MeterReadingPreviewRequest,
)
from backend.app.services.auth import bootstrap_admin, create_employee
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    create_fuel_record,
    preview_meter_reading,
)
from backend.app.services.global_meter import (
    create_global_meter_event,
    get_or_create_global_meter_state,
)
from backend.app.services.meter_photos import (
    InvalidMeterVerification,
    verify_meter_photo,
)
from backend.app.services.meter_readings import (
    assess_meter_readings,
    milli_litres_to_decimal,
    parse_total_raw_digits,
)
from backend.app.services.vehicles import create_vehicle


class MeterReadingConversionTests(unittest.TestCase):
    def test_total_raw_digits_use_three_decimal_places(self) -> None:
        self.assertEqual(parse_total_raw_digits("000000"), 0)
        self.assertEqual(
            milli_litres_to_decimal(parse_total_raw_digits("261789")),
            Decimal("261.789"),
        )

    def test_delta_is_exact_and_decreases_are_flagged(self) -> None:
        increasing = assess_meter_readings(
            fill_milli_litres=None,
            previous_total_milli_litres=261_563,
            cumulative_total_milli_litres=261_789,
            source="MANUAL",
        )
        decreased = assess_meter_readings(
            fill_milli_litres=None,
            previous_total_milli_litres=261_789,
            cumulative_total_milli_litres=261_563,
            source="MANUAL",
        )

        self.assertEqual(increasing.delta_milli_litres, 226)
        self.assertEqual(increasing.fill_milli_litres, 226)
        self.assertEqual(milli_litres_to_decimal(increasing.fill_milli_litres), Decimal("0.226"))
        self.assertTrue(any("decreased" in warning for warning in decreased.warnings))
        self.assertIsNone(decreased.fill_milli_litres)


class MeterReadingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.photo_sequence = 0

    def tearDown(self) -> None:
        self.engine.dispose()

    def _create_accounts_and_vehicle(
        self, session: Session
    ) -> tuple[Employee, Employee, Vehicle]:
        admin = bootstrap_admin(
            session,
            "meter-admin@example.test",
            "Meter Admin",
            "temporary-admin-password",
        )
        employee = create_employee(
            session,
            "meter-worker@example.test",
            "Meter Worker",
            "temporary-worker-password",
        )
        vehicle = create_vehicle(session, "MT12 TST")
        vehicle.fuel_type = "Diesel"
        vehicle.tank_capacity = 60
        employee.vehicles.append(vehicle)
        session.flush()
        return admin, employee, vehicle

    @staticmethod
    def _set_global_total(session: Session, total_milli_litres: int) -> None:
        session.add(
            GlobalMeterState(
                id=1,
                current_cumulative_total_litres=float(
                    milli_litres_to_decimal(total_milli_litres)
                ),
                current_total_integer=total_milli_litres,
                current_total_raw_digits=str(total_milli_litres),
                revision=1,
            )
        )
        session.flush()

    def _create_photo(
        self,
        session: Session,
        employee: Employee,
        vehicle: Vehicle,
        *,
        ocr_digits: str | None,
        ocr_warnings: list[str] | None = None,
        ocr_status: str = "uncertain",
    ) -> MeterPhoto:
        self.photo_sequence += 1
        now = datetime.now(timezone.utc)
        token = f"meter-photo-session-{self.photo_sequence}"
        qr_session = QrSession(
            token_hash=sha256(token.encode("utf-8")).hexdigest(),
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        session.add(qr_session)
        session.flush()
        photo = MeterPhoto(
            qr_session_id=qr_session.id,
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            storage_key=f"test-meter-photo-{self.photo_sequence}",
            content_type="image/jpeg",
            size_bytes=1,
            sha256=sha256(token.encode("utf-8")).hexdigest(),
            uploaded_at=now,
            ocr_status=ocr_status,
            ocr_provider="google_vision",
            ocr_cumulative_total_litres=(
                float(Decimal(ocr_digits).scaleb(-3))
                if ocr_digits is not None
                else None
            ),
            ocr_cumulative_total_confidence=96 if ocr_digits is not None else None,
            ocr_cumulative_total_raw_digits=ocr_digits,
            ocr_cumulative_total_decimal_position=(
                max(0, len(ocr_digits) - 3) if ocr_digits is not None else None
            ),
            ocr_warnings=ocr_warnings or [],
        )
        session.add(photo)
        session.flush()
        return photo

    def test_admin_must_establish_baseline_before_transaction_delta(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin, employee, vehicle = self._create_accounts_and_vehicle(session)

            create_global_meter_event(
                session,
                admin,
                "baseline",
                Decimal("261.563"),
                "Verified initial PIUSI TOTAL reading.",
            )
            reading = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    cumulativeTotalRawDigits="261789",
                    confirmed=True,
                    calculatedFillConfirmed=True,
                    odometerMiles=1000,
                ),
            )

            self.assertIsInstance(reading, FuelRecord)
            self.assertEqual(reading.current_fill_milli_litres, 226)
            self.assertEqual(reading.cumulative_total_integer, 261789)
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                261789,
            )

    def test_no_baseline_never_guesses_fuel_amount(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            with self.assertRaisesRegex(FuelSubmissionError, "establish the meter baseline"):
                create_fuel_record(
                    session,
                    employee,
                    FuelRecordCreate(
                        cumulativeTotalRawDigits="261789",
                        confirmed=True,
                        odometerMiles=1000,
                    ),
                )

    def test_preview_returns_exact_previous_total_and_delta(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, _, _ = self._create_accounts_and_vehicle(session)
            self._set_global_total(session, 261563)

            preview = preview_meter_reading(
                session,
                MeterReadingPreviewRequest(
                    cumulativeTotalRawDigits="261789"
                ),
            )

            self.assertEqual(preview["previous_total_milli_litres"], 261563)
            self.assertEqual(preview["cumulative_total_milli_litres"], 261789)
            self.assertEqual(preview["delta_milli_litres"], 226)
            self.assertEqual(preview["fill_milli_litres"], 226)
            self.assertNotIn("top_current_fill_milli_litres", preview)

    def test_photo_correction_preserves_original_ocr_and_updates_total_once(self) -> None:
        disagreement = (
            "Google Vision and OpenCV disagree on the TOTAL-row digits; manual review is required."
        )
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            self._set_global_total(session, 261563)
            photo = self._create_photo(
                session,
                employee,
                vehicle,
                ocr_digits="261798",
                ocr_warnings=[disagreement],
            )

            verified = verify_meter_photo(
                session,
                employee,
                photo.id,
                cumulative_total_raw_digits="261789",
            )

            self.assertEqual(verified.ocr_cumulative_total_raw_digits, "261798")
            self.assertEqual(verified.cumulative_total_raw_digits, "261789")
            self.assertEqual(verified.cumulative_total_integer, 261789)
            self.assertEqual(verified.current_fill_milli_litres, 226)
            self.assertTrue(verified.cumulative_total_manually_corrected)
            self.assertIn(disagreement, verified.reading_warnings)

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
            self.assertEqual(record.current_fill_milli_litres, 226)
            self.assertEqual(record.cumulative_total_integer, 261789)
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                261789,
            )
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

    def test_unchanged_ocr_total_is_marked_not_manually_corrected(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            self._set_global_total(session, 261563)
            photo = self._create_photo(
                session,
                employee,
                vehicle,
                ocr_digits="261789",
                ocr_status="ready",
            )

            verified = verify_meter_photo(session, employee, photo.id)

            self.assertEqual(verified.cumulative_total_raw_digits, "261789")
            self.assertFalse(verified.cumulative_total_manually_corrected)

    def test_lower_total_waits_for_review_without_advancing_global_total(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            self._set_global_total(session, 100000)
            photo = self._create_photo(
                session,
                employee,
                vehicle,
                ocr_digits="099999",
                ocr_status="ready",
            )
            verify_meter_photo(session, employee, photo.id)

            review = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meterPhotoId=photo.id,
                    calculatedFillConfirmed=True,
                    odometerMiles=1000,
                ),
            )

            self.assertIsInstance(review, MeterReadingReview)
            self.assertIsNone(review.current_fill_milli_litres)
            self.assertTrue(any("decreased" in warning for warning in review.warnings))
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                100000,
            )

    def test_suspicious_large_increase_waits_for_review(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            self._set_global_total(session, 100000)
            photo = self._create_photo(
                session,
                employee,
                vehicle,
                ocr_digits="300001",
                ocr_status="ready",
            )
            verify_meter_photo(session, employee, photo.id)

            review = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meterPhotoId=photo.id,
                    calculatedFillConfirmed=True,
                    odometerMiles=1000,
                ),
            )

            self.assertIsInstance(review, MeterReadingReview)
            self.assertEqual(review.current_fill_milli_litres, 200001)
            self.assertTrue(any("alert threshold" in warning for warning in review.warnings))
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                100000,
            )

    def test_short_total_is_rejected_as_missing_digits(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            photo = self._create_photo(
                session,
                employee,
                vehicle,
                ocr_digits="261789",
            )

            with self.assertRaisesRegex(InvalidMeterVerification, "at least six digits"):
                verify_meter_photo(
                    session,
                    employee,
                    photo.id,
                    cumulative_total_raw_digits="61789",
                )
            self.assertIsNone(photo.verified_at)


if __name__ == "__main__":
    unittest.main()
