import importlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
from sqlalchemy import create_engine, inspect, text, update
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
from backend.app.api.routers.fuel_records import (
    create_fuel_record as create_fuel_record_route,
)
from backend.app.schemas.fuel_record import FuelRecordCreate
from backend.app.services.auth import bootstrap_admin, create_employee
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    create_fuel_record,
    decide_meter_reading_review,
)
from backend.app.services.global_meter import (
    GlobalMeterConcurrentUpdate,
    get_or_create_global_meter_state,
    update_global_meter_after_fill,
)
from backend.app.services.meter_photos import (
    InvalidMeterVerification,
    store_meter_photo,
    verify_meter_photo,
)
from backend.app.services.meter_readings import (
    assess_meter_readings,
    milli_litres_to_decimal,
    parse_fill_raw_digits,
    parse_total_raw_digits,
)
from backend.app.services.vehicles import create_vehicle


class MeterReadingConversionTests(unittest.TestCase):
    def test_fill_digits_are_exact_millilitres_and_totals_are_integers(self) -> None:
        self.assertEqual(
            milli_litres_to_decimal(parse_fill_raw_digits("22032")),
            Decimal("22.032"),
        )
        self.assertEqual(
            milli_litres_to_decimal(parse_fill_raw_digits("77001")),
            Decimal("77.001"),
        )
        self.assertEqual(
            milli_litres_to_decimal(parse_fill_raw_digits("100000")),
            Decimal("100.000"),
        )
        self.assertEqual(parse_total_raw_digits("261563"), 261563)
        self.assertEqual(
            milli_litres_to_decimal(parse_total_raw_digits("261563")),
            Decimal("261.563"),
        )

    def test_zero_oversize_unchanged_and_decreased_readings_are_flagged(self) -> None:
        zero = assess_meter_readings(
            fill_milli_litres=0,
            previous_total_milli_litres=1_000_000,
            cumulative_total_milli_litres=1_000_000,
            source="manual",
        )
        too_large = assess_meter_readings(
            fill_milli_litres=100001,
            previous_total_milli_litres=1_000_000,
            cumulative_total_milli_litres=1_100_000,
            source="manual",
        )
        decreased = assess_meter_readings(
            fill_milli_litres=1000,
            previous_total_milli_litres=1_000_000,
            cumulative_total_milli_litres=999_000,
            source="ocr",
        )

        self.assertTrue(any("greater than zero" in warning for warning in zero.warnings))
        self.assertTrue(any("unchanged" in warning for warning in zero.warnings))
        self.assertTrue(any("100 litre limit" in warning for warning in too_large.warnings))
        self.assertTrue(any("decreased" in warning for warning in decreased.warnings))

    def test_first_total_and_reconciliation_tolerance(self) -> None:
        first = assess_meter_readings(
            fill_milli_litres=10000,
            previous_total_milli_litres=None,
            cumulative_total_milli_litres=1_000_000,
            source="manual",
        )
        reconciled = assess_meter_readings(
            fill_milli_litres=22032,
            previous_total_milli_litres=1_000_000,
            cumulative_total_milli_litres=1_022_000,
            source="ocr",
        )
        discrepant = assess_meter_readings(
            fill_milli_litres=150000,
            previous_total_milli_litres=1_000_000,
            cumulative_total_milli_litres=1_200_000,
            source="ocr",
        )

        self.assertTrue(any("no previous global total" in warning for warning in first.warnings))
        self.assertEqual(reconciled.reconciliation_status, "reconciled")
        self.assertEqual(reconciled.delta_milli_litres, 22_000)
        self.assertEqual(reconciled.fill_milli_litres, 22000)
        self.assertEqual(reconciled.top_current_fill_milli_litres, 22032)
        self.assertEqual(reconciled.fill_source, "GLOBAL_DIFFERENCE")
        self.assertTrue(discrepant.warnings)


class MeterReadingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite://")
        Base.metadata.create_all(self.engine)

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

    def _manual_request(
        self,
        odometer: float,
        total: str,
        fill: str | None,
        *,
        calculated_confirmed: bool = False,
    ) -> FuelRecordCreate:
        values: dict[str, object] = {
            "odometerMiles": odometer,
            "cumulativeTotalRawDigits": total,
            "confirmed": True,
            "calculatedFillConfirmed": calculated_confirmed,
        }
        if fill is not None:
            values["currentFillRawDigits"] = fill
        return FuelRecordCreate.model_validate(values)

    def test_baseline_and_reconciled_fill_are_saved_without_review(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            initial = create_fuel_record(
                session,
                employee,
                self._manual_request(1000, "001000000", "10000"),
            )
            self.assertIsInstance(initial, FuelRecord)
            self.assertEqual(initial.previous_global_total_integer, None)
            self.assertEqual(initial.current_fill_milli_litres, 10000)
            self.assertEqual(initial.meter_check_status, "baseline")
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_raw_digits,
                "001000000",
            )

            accepted = create_fuel_record(
                session,
                employee,
                self._manual_request(
                    1100, "001022000", "22032", calculated_confirmed=True
                ),
            )
            self.assertIsInstance(accepted, FuelRecord)
            self.assertEqual(accepted.current_fill_milli_litres, 22000)
            self.assertEqual(accepted.top_current_fill_milli_litres, 22032)
            self.assertEqual(accepted.current_fill_raw_digits, "22032")
            self.assertEqual(accepted.cumulative_total_integer, 1_022_000)
            self.assertEqual(accepted.cumulative_total_raw_digits, "001022000")
            self.assertEqual(accepted.meter_reading_source, "GLOBAL_DIFFERENCE")
            self.assertEqual(accepted.reading_source, "MANUAL")
            self.assertEqual(accepted.meter_check_status, "matched")

            duplicate_request = self._manual_request(1100, "001022000", "22032")
            with self.assertRaisesRegex(FuelSubmissionError, "already been saved"):
                create_fuel_record(session, employee, duplicate_request)
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                1_022_000,
            )

    def test_20000_raw_fill_reconciles_as_20_litres(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            baseline = create_fuel_record(
                session,
                employee,
                self._manual_request(1000, "100000", "50"),
            )
            self.assertIsInstance(baseline, FuelRecord)
            self.assertEqual(baseline.current_fill_milli_litres, 50)

            next_fill = create_fuel_record(
                session,
                employee,
                self._manual_request(
                    1050, "120000", "20000", calculated_confirmed=True
                ),
            )

            self.assertIsInstance(next_fill, FuelRecord)
            self.assertEqual(next_fill.current_fill_milli_litres, 20_000)
            self.assertEqual(next_fill.top_current_fill_milli_litres, 20_000)
            self.assertEqual(next_fill.cumulative_total_integer, 120_000)
            self.assertEqual(next_fill.meter_check_status, "matched")

    def test_api_rejects_fuel_submission_without_meter_photo(self) -> None:
        from fastapi import HTTPException

        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            request = self._manual_request(1000, "100000", "20000")

            with self.assertRaises(HTTPException) as raised:
                create_fuel_record_route(request, session, employee)

            self.assertEqual(raised.exception.status_code, 422)
            self.assertIn("meter photo is required", raised.exception.detail)

    def test_over_100_calculated_fill_is_rejected_without_review(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            baseline = create_fuel_record(
                session,
                employee,
                self._manual_request(1000, "1000000", "10000"),
            )
            self.assertIsInstance(baseline, FuelRecord)

            with self.assertRaisesRegex(FuelSubmissionError, "100 litre limit"):
                create_fuel_record(
                    session,
                    employee,
                    self._manual_request(
                        1100, "1200000", None, calculated_confirmed=True
                    ),
                )
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                1_000_000,
            )

    def test_missing_top_is_calculated_and_mismatch_waits_for_admin_review(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            baseline = create_fuel_record(
                session, employee, self._manual_request(1000, "1000000", "10000")
            )
            self.assertIsInstance(baseline, FuelRecord)

            missing_top = create_fuel_record(
                session,
                employee,
                self._manual_request(
                    1050, "1025000", None, calculated_confirmed=True
                ),
            )
            self.assertIsInstance(missing_top, FuelRecord)
            self.assertEqual(missing_top.current_fill_milli_litres, 25000)
            self.assertIsNone(missing_top.top_current_fill_milli_litres)
            self.assertEqual(missing_top.meter_reading_source, "GLOBAL_DIFFERENCE")

            mismatch = create_fuel_record(
                session,
                employee,
                self._manual_request(
                    1100, "1045000", "15000", calculated_confirmed=True
                ),
            )
            self.assertIsInstance(mismatch, MeterReadingReview)
            self.assertEqual(mismatch.current_fill_milli_litres, 20000)
            self.assertEqual(mismatch.top_current_fill_milli_litres, 15000)
            self.assertTrue(
                any("does not match" in item for item in mismatch.warnings)
            )
            self.assertEqual(mismatch.status, "pending")
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                1_025_000,
            )

    def test_decreased_global_total_waits_for_admin_review_without_advancing_total(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            initial = create_fuel_record(
                session, employee, self._manual_request(1000, "1000000", "10000")
            )
            self.assertIsInstance(initial, FuelRecord)
            lowered = create_fuel_record(
                session, employee, self._manual_request(1100, "999000", "1000")
            )
            self.assertIsInstance(lowered, MeterReadingReview)
            self.assertTrue(
                any("decreased" in warning for warning in lowered.warnings)
            )
            self.assertEqual(lowered.current_fill_milli_litres, 1000)
            self.assertEqual(lowered.status, "pending")
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                1_000_000,
            )

    def test_warning_submission_waits_for_admin_review_and_approval_saves_record(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, _ = self._create_accounts_and_vehicle(session)
            baseline = create_fuel_record(
                session, employee, self._manual_request(1000, "1000000", "10000")
            )
            self.assertIsInstance(baseline, FuelRecord)
            state = get_or_create_global_meter_state(session)
            initial_revision = state.revision
            warning_record = create_fuel_record(
                session,
                employee,
                self._manual_request(
                    1100, "1025000", "15000", calculated_confirmed=True
                ),
            )
            self.assertIsInstance(warning_record, MeterReadingReview)
            self.assertEqual(state.current_total_integer, 1_000_000)
            self.assertEqual(state.revision, initial_revision)
            self.assertEqual(session.query(FuelRecord).count(), 1)

            approved = decide_meter_reading_review(
                session,
                session.query(Employee).filter_by(role="admin").one(),
                warning_record.id,
                "approve",
                "Reviewed the meter photograph and confirmed the mismatch.",
            )
            self.assertEqual(approved.status, "approved")
            self.assertIsNotNone(approved.fuel_record_id)
            self.assertEqual(state.current_total_integer, 1_025_000)
            self.assertEqual(session.query(FuelRecord).count(), 2)

    def test_flagged_baseline_approval_saves_the_fill_and_baseline_event(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin, employee, vehicle = self._create_accounts_and_vehicle(session)
            now = datetime.now(timezone.utc)
            qr_session = QrSession(
                token_hash=sha256(b"flagged-baseline-session").hexdigest(),
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
                storage_key="flagged-baseline-photo",
                content_type="image/jpeg",
                size_bytes=1,
                sha256=sha256(b"flagged-photo").hexdigest(),
                uploaded_at=now,
                ocr_status="skipped",
                ocr_warnings=["The uploaded reading needs administrator review."],
                current_fill_milli_litres=10_000,
                top_current_fill_milli_litres=10_000,
                cumulative_total_integer=1_000_000,
                current_fill_raw_digits="10000",
                cumulative_total_raw_digits="1000000",
                reading_source="MANUAL",
                verified_at=now,
            )
            session.add(photo)
            session.flush()
            review = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meterPhotoId=photo.id,
                    odometerMiles=1000,
                    calculatedFillConfirmed=True,
                ),
            )
            self.assertIsInstance(review, MeterReadingReview)
            self.assertEqual(session.query(FuelRecord).count(), 0)

            approved = decide_meter_reading_review(
                session,
                admin,
                review.id,
                "approve",
                "Reviewed the original photo and confirmed the baseline.",
            )
            self.assertEqual(approved.status, "approved")
            self.assertIsNotNone(approved.fuel_record_id)
            self.assertIsNotNone(approved.global_meter_event_id)
            self.assertEqual(session.query(FuelRecord).count(), 1)
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                1_000_000,
            )

    def test_manual_photo_skips_ocr_and_missing_top_is_calculated(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), color="white").save(image_buffer, format="PNG")

        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=1000,
                    current_total_integer=1_000_000,
                    current_total_raw_digits="001000000",
                    revision=1,
                )
            )
            token = "offline-manual-meter-session"
            qr_session = QrSession(
                token_hash=sha256(token.encode("utf-8")).hexdigest(),
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            session.add(qr_session)
            session.flush()

            with TemporaryDirectory() as upload_directory:
                with (
                    patch(
                        "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                        Path(upload_directory),
                    ),
                    patch(
                        "backend.app.services.meter_photos.extract_meter_readings",
                        side_effect=AssertionError("Manual mode must not invoke OCR."),
                    ) as ocr,
                ):
                    photo, _ = store_meter_photo(
                        session,
                        employee,
                        token,
                        image_buffer.getvalue(),
                        "image/png",
                        reading_mode="manual",
                    )
                    verified = verify_meter_photo(
                        session,
                        employee,
                        photo.id,
                        cumulative_total_raw_digits="001025000",
                    )

                ocr.assert_not_called()
                self.assertEqual(photo.ocr_status, "skipped")
                self.assertEqual(verified.reading_source, "MANUAL")
                self.assertEqual(verified.fill_source, "GLOBAL_DIFFERENCE")
                self.assertEqual(verified.fill_calculation, "global_total_difference")
                self.assertEqual(verified.current_fill_milli_litres, 25000)
                self.assertEqual(
                    verified.cumulative_total_raw_digits, "001025000"
                )

                record = create_fuel_record(
                    session,
                    employee,
                    FuelRecordCreate(
                        meterPhotoId=photo.id,
                        odometerMiles=1100,
                        calculatedFillConfirmed=True,
                    ),
                )
                self.assertIsInstance(record, FuelRecord)
                self.assertEqual(
                    get_or_create_global_meter_state(session).current_total_integer,
                    1_025_000,
                )

    def test_photo_verification_rejects_a_missing_cumulative_total(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            now = datetime.now(timezone.utc)
            qr_session = QrSession(
                token_hash=sha256(b"missing-total-session").hexdigest(),
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
                storage_key="missing-total-photo",
                content_type="image/jpeg",
                size_bytes=1,
                sha256=sha256(b"photo").hexdigest(),
                uploaded_at=now,
            )
            session.add(photo)
            session.flush()

            with self.assertRaisesRegex(
                InvalidMeterVerification, "global cumulative total is missing"
            ):
                verify_meter_photo(
                    session,
                    employee,
                    photo.id,
                    current_fill_raw_digits="22032",
                )
            self.assertIsNone(photo.verified_at)

    def test_confirmed_ocr_values_without_raw_digits_save_without_admin_review(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            now = datetime.now(timezone.utc)
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=239.531,
                    current_total_integer=239_531,
                    current_total_raw_digits="239531",
                    revision=1,
                )
            )
            qr_session = QrSession(
                token_hash=sha256(b"confirmed-ocr-session").hexdigest(),
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
                storage_key="confirmed-ocr-photo",
                content_type="image/jpeg",
                size_bytes=1,
                sha256=sha256(b"confirmed-ocr-photo").hexdigest(),
                uploaded_at=now,
                ocr_status="uncertain",
                ocr_current_fill_litres=22032,
                ocr_cumulative_total_litres=261.563,
                ocr_warnings=[
                    "The current-fill digits need manual review.",
                    "The cumulative-total digits need manual review.",
                ],
            )
            session.add(photo)
            session.flush()

            verified = verify_meter_photo(
                session,
                employee,
                photo.id,
                current_fill_raw_digits="22032",
                cumulative_total_raw_digits="261563",
            )
            self.assertEqual(verified.ocr_warnings, [])

            record = create_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meterPhotoId=photo.id,
                    odometerMiles=1000,
                ),
            )
            self.assertIsInstance(record, FuelRecord)
            self.assertEqual(record.cumulative_total_integer, 261_563)

    def test_concurrent_global_meter_change_fails_compare_and_swap(self) -> None:
        with Session(self.engine) as session, session.begin():
            _, employee, vehicle = self._create_accounts_and_vehicle(session)
            state = GlobalMeterState(
                id=1,
                current_cumulative_total_litres=1000,
                current_total_integer=1_000_000,
                current_total_raw_digits="1000000",
                revision=3,
            )
            session.add(state)
            session.flush()
            stale_revision = state.revision
            session.connection().execute(
                update(GlobalMeterState)
                .where(GlobalMeterState.id == 1)
                .values(revision=stale_revision + 1)
            )
            record = FuelRecord(
                id=42,
                cumulative_total_litres=1020,
                cumulative_total_integer=1_020_000,
                previous_global_total_integer=1_000_000,
                cumulative_total_raw_digits="1020000",
            )

            with self.assertRaises(GlobalMeterConcurrentUpdate):
                update_global_meter_after_fill(
                    session,
                    state,
                    record,
                    employee,
                    vehicle,
                    datetime.now(timezone.utc),
                )

    def test_historical_readings_are_not_changed_by_additive_migration(self) -> None:
        migration = importlib.import_module(
            "backend.migrations.versions.0016_piusi_exact_readings_and_reviews"
        )
        next_migration = importlib.import_module(
            "backend.migrations.versions.0017_global_fill_source_and_top_evidence"
        )
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE employees (id INTEGER PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE vehicles (id INTEGER PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE vehicle_odometer_corrections (id INTEGER PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE meter_photos (id INTEGER PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE fuel_records (
                        id INTEGER PRIMARY KEY,
                        current_fill_litres FLOAT,
                        cumulative_total_litres FLOAT
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE global_meter_state (
                        id INTEGER PRIMARY KEY,
                        current_cumulative_total_litres FLOAT
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE global_meter_events (
                        id INTEGER PRIMARY KEY,
                        event_type VARCHAR(16) NOT NULL,
                        CONSTRAINT ck_global_meter_events_event_type
                            CHECK (event_type IN ('reset', 'replacement'))
                    )
                    """
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO fuel_records
                            (id, current_fill_litres, cumulative_total_litres)
                        VALUES (1, 22.032, 123456.75)
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO global_meter_state
                            (id, current_cumulative_total_litres)
                        VALUES (1, 123456.75)
                        """
                    )
                )
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()

                historical = connection.execute(
                    text(
                        """
                        SELECT current_fill_litres, cumulative_total_litres
                        FROM fuel_records WHERE id = 1
                        """
                    )
                ).one()
                exact_fields = connection.execute(
                    text(
                        """
                        SELECT current_fill_milli_litres, cumulative_total_integer
                        FROM fuel_records WHERE id = 1
                        """
                    )
                ).one()
                self.assertEqual(historical, (22.032, 123456.75))
                self.assertEqual(exact_fields, (None, None))
                self.assertIn(
                    "meter_reading_reviews",
                    inspect(connection).get_table_names(),
                )
                with Operations.context(context):
                    next_migration.upgrade()
                self.assertIn(
                    "top_current_fill_milli_litres",
                    {column["name"] for column in inspect(connection).get_columns("fuel_records")},
                )
                self.assertIn(
                    "reading_source",
                    {column["name"] for column in inspect(connection).get_columns("fuel_records")},
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            "SELECT current_fill_milli_litres, cumulative_total_integer "
                            "FROM fuel_records WHERE id = 1"
                        )
                    ).one(),
                    (None, None),
                )

                with Operations.context(context):
                    next_migration.downgrade()
                with Operations.context(context):
                    migration.downgrade()
                restored = connection.execute(
                    text(
                        "SELECT current_fill_litres, cumulative_total_litres "
                        "FROM fuel_records WHERE id = 1"
                    )
                ).one()
                self.assertEqual(restored, historical)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
