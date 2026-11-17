import base64
import json
import os
import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from http.cookies import SimpleCookie
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Response
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.app.cli import reset_production_data
from backend.app.api.routers.auth import login as login_endpoint
from backend.app.api.routers.auth import logout as logout_endpoint
from backend.app.api.routers.admin import (
    add_employee as add_employee_endpoint,
    add_vehicle as add_vehicle_endpoint,
    change_employee_role as change_employee_role_endpoint,
    change_employee_status as change_employee_status_endpoint,
)
from backend.app.api.routers.meter_photos import (
    read_meter_photo_content as read_meter_photo_content_endpoint,
    start_vehicle_photo_session as start_vehicle_photo_session_endpoint,
)
from backend.app.api.routers.fuel_records import read_fuel_records
from backend.app.api.dependencies import (
    get_current_employee,
    require_admin,
    require_management,
)
from backend.app.main import app
from backend.app.api.routers.vehicles import (
    lookup_vehicle,
    my_vehicle,
    my_vehicle_fuel_records,
    vehicle_registration_suggestions,
)
from backend.app.core.config import (
    SESSION_COOKIE_NAME,
    get_database_url,
    get_migration_database_url,
)
from backend.app.core.rate_limit import LoginRateLimiter, login_rate_limiter
from backend.app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from backend.app.services.dashboard import get_dashboard_status
from backend.app.db.base import Base
from backend.app.db.session import create_database_engine, get_db_session
from backend.app.models import (
    Employee,
    EmployeeSession,
    FuelRecord,
    GlobalMeterEvent,
    GlobalMeterState,
    MeterPhoto,
    MeterReadingReview,
    QrSession,
    Vehicle,
    VehicleMeterEvent,
    VehicleOdometerCorrection,
)
from backend.app.repositories.meter_photos import get_qr_session_by_hash
from backend.app.schemas.auth import LoginRequest
from backend.app.schemas.employee import (
    EmployeeCreate,
    EmployeeRoleUpdate,
    EmployeeStatusUpdate,
)
from backend.app.schemas.admin_dashboard import (
    AdminEmployeeRead,
    AdminFuelSummaryRead,
)
from backend.app.schemas.fuel_record import FuelRecordCreate, FuelRecordRead
from backend.app.schemas.meter_photo import (
    MeterPhotoSessionCreate,
    MeterPhotoVerify,
)
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    MeterPhotoNotOwned,
    create_fuel_record as save_fuel_record,
    decide_meter_reading_review,
)
from backend.app.schemas.vehicle import VehicleCreate, VehicleRead
from backend.app.services.auth import (
    authenticate_employee,
    bootstrap_admin,
    create_employee,
)
from backend.app.services.demo_data import (
    DEMO_NCT_DAYS_REMAINING,
    DEMO_EMPLOYEE_NAMES,
    DEMO_PASSWORD,
    LEGACY_DEMO_EMPLOYEE_NAMES,
    reset_demo_data,
    seed_demo_data,
)
from backend.app.services.nct import get_nct_alerts, list_vehicle_nct, update_vehicle_nct
from backend.app.services.employee_sessions import (
    create_employee_session,
    get_employee_for_session,
)
from backend.app.services.fuel_records import get_fuel_records
from backend.app.services.inventory import get_inventory_status
from backend.app.services.history_cleanup import clear_history
from backend.app.services.meter_photos import (
    InvalidMeterVerification,
    InvalidQrSession,
    UnsupportedMeterPhotoType,
    create_assigned_vehicle_photo_session,
    create_qr_session,
    create_vehicle_photo_session,
    store_meter_photo,
    validate_meter_photo,
    verify_meter_photo,
)
from backend.app.services.meter_ocr import (
    MeterOcrResult,
    extract_meter_readings,
    _extract_google_vision_readings,
    parse_meter_ocr_data,
)
from backend.app.services.vehicle_meter_events import authorize_odometer_correction
from backend.app.services.global_meter import (
    create_global_meter_event,
    get_or_create_global_meter_state,
    get_global_meter_summary,
    list_global_meter_history,
)
from backend.app.services.admin_dashboard import (
    AdminEmployeeNotFound,
    InvalidAdminDateRange,
    get_admin_fuel_summary,
    list_admin_employees,
    list_employee_fuel_records,
)
from backend.app.services.application_reset import (
    clear_operational_data,
    reset_application_data,
)
from backend.app.services.vehicles import (
    create_vehicle,
    identify_vehicle,
    issue_vehicle_qr,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self._test_photo_sequence = 0
        self.ocr_provider_patch = patch.dict(
            os.environ, {"FUEL_OCR_PROVIDER": "tesseract"}
        )
        self.ocr_provider_patch.start()
        self.addCleanup(self.ocr_provider_patch.stop)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_list_admin_employees_orders_case_insensitively(self) -> None:
        with Session(self.engine) as session, session.begin():
            create_employee(session, "zoe@example.com", "zoe", "password123456")
            create_employee(session, "alice@example.com", "Alice", "password123456")
            create_employee(session, "bob@example.com", "bob", "password123456")

        with Session(self.engine) as session:
            employees = list_admin_employees(session)

        self.assertEqual([employee.name for employee in employees], [
            "Alice",
            "bob",
            "zoe",
        ])

    def test_application_reset_preserves_admin_and_clears_all_app_data(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin = bootstrap_admin(
                session, "admin@example.com", "Admin", "admin-password-123"
            )
            employee = create_employee(
                session, "employee@example.com", "Employee", "employee-password-123"
            )
            vehicle = create_vehicle(session, "AB12 CDE")
            employee.vehicles.append(vehicle)
            session.flush()

            qr_session = QrSession(
                token_hash="a" * 64,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(qr_session)
            session.flush()
            photo_key = "meter-photo-test.jpg"
            photo = MeterPhoto(
                qr_session_id=qr_session.id,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                storage_key=photo_key,
                content_type="image/jpeg",
                size_bytes=1,
                sha256="b" * 64,
                uploaded_at=datetime.now(timezone.utc),
            )
            session.add(photo)
            session.flush()
            session.add(
                FuelRecord(
                    reg_number=vehicle.registration_number,
                    fuel_type="Diesel",
                    first_name="Employee",
                    surname="Test",
                    mileage_miles=100,
                    capacity=60,
                    litres=20,
                    employee_id=employee.id,
                    vehicle_id=vehicle.id,
                    meter_photo_id=photo.id,
                )
            )
            session.flush()

            photo_keys = reset_application_data(session)

            self.assertEqual(photo_keys, [photo_key])
            self.assertEqual(admin.role, "admin")

        with Session(self.engine) as session:
            employees = list(session.scalars(select(Employee)))
            self.assertEqual(
                [(employee.email, employee.role) for employee in employees],
                [("admin@example.com", "admin")],
            )
            for table in Base.metadata.sorted_tables:
                if table.name == Employee.__tablename__:
                    continue
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(table)),
                    0,
                    table.name,
                )

    def test_application_reset_refuses_to_run_without_one_admin(self) -> None:
        with Session(self.engine) as session, session.begin():
            create_employee(
                session, "employee@example.com", "Employee", "employee-password-123"
            )

        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError, "exactly one administrator"):
                reset_application_data(session)
            employees = list(session.scalars(select(Employee)))

        self.assertEqual(len(employees), 1)

    def test_operational_data_clear_preserves_users_and_vehicles(self) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            admin = bootstrap_admin(
                session, "admin@example.com", "Admin", "admin-password-123"
            )
            employee = create_employee(
                session, "employee@example.com", "Employee", "employee-password-123"
            )
            vehicle = create_vehicle(session, "AB12 CDE")
            vehicle.cumulative_total_litres = 1250
            vehicle.meter_epoch = 2
            employee.vehicles.append(vehicle)
            session.flush()

            qr_session = QrSession(
                token_hash="a" * 64,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            session.add(qr_session)
            session.flush()
            photo = MeterPhoto(
                qr_session_id=qr_session.id,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                storage_key="meter-photo-clear-test.jpg",
                content_type="image/jpeg",
                size_bytes=1,
                sha256="b" * 64,
                uploaded_at=now,
            )
            session.add(photo)
            correction = VehicleOdometerCorrection(
                vehicle_id=vehicle.id,
                authorized_by_employee_id=admin.id,
                authorized_odometer_miles=1200,
                previous_odometer_miles=1000,
                notes="Cleanup test",
                created_at=now,
            )
            session.add(correction)
            session.flush()
            record = FuelRecord(
                reg_number=vehicle.registration_number,
                fuel_type="Diesel",
                first_name="Employee",
                surname="Test",
                mileage_miles=1100,
                capacity=60,
                litres=20,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                meter_photo_id=photo.id,
                odometer_correction_id=correction.id,
            )
            global_event = GlobalMeterEvent(
                event_type="baseline",
                baseline_cumulative_total_litres=1250,
                authorized_by_employee_id=admin.id,
                occurred_at=now,
                notes="Cleanup test",
            )
            session.add_all((record, global_event))
            session.flush()
            session.add_all(
                (
                    GlobalMeterState(
                        id=1,
                        current_cumulative_total_litres=1250,
                        last_transaction_id=record.id,
                        last_employee_id=employee.id,
                        last_vehicle_id=vehicle.id,
                        last_event_id=global_event.id,
                    ),
                    VehicleMeterEvent(
                        vehicle_id=vehicle.id,
                        created_by_employee_id=employee.id,
                        meter_epoch=2,
                        event_type="reset",
                        baseline_cumulative_total_litres=1250,
                        occurred_at=now,
                        notes="Cleanup test",
                    ),
                    MeterReadingReview(
                        employee_id=employee.id,
                        vehicle_id=vehicle.id,
                        meter_photo_id=photo.id,
                        odometer_correction_id=correction.id,
                        odometer_miles=1100,
                        reading_source="photo",
                        warnings=[],
                        global_meter_revision=1,
                        submitted_at=now,
                        fuel_record_id=record.id,
                        global_meter_event_id=global_event.id,
                    ),
                    EmployeeSession(
                        employee_id=employee.id,
                        token_hash="c" * 64,
                        created_at=now,
                        expires_at=now + timedelta(days=1),
                    ),
                )
            )
            session.flush()

            photo_keys = clear_operational_data(session)

            self.assertEqual(photo_keys, ["meter-photo-clear-test.jpg"])

        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Employee)), 2
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Vehicle)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(EmployeeSession)), 1
            )
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(
                        Base.metadata.tables["employee_vehicles"]
                    )
                ),
                1,
            )
            vehicle = session.scalar(select(Vehicle))
            self.assertIsNotNone(vehicle)
            self.assertIsNone(vehicle.cumulative_total_litres)
            self.assertEqual(vehicle.meter_epoch, 0)
            for model in (
                FuelRecord,
                GlobalMeterEvent,
                GlobalMeterState,
                MeterPhoto,
                MeterReadingReview,
                QrSession,
                VehicleMeterEvent,
                VehicleOdometerCorrection,
            ):
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(model)),
                    0,
                    model.__tablename__,
                )

    def test_production_reset_command_refuses_non_production_environment(self) -> None:
        with patch.dict(os.environ, {"FUEL_ENV": "development"}, clear=True):
            with patch("builtins.input") as input_mock:
                result = reset_production_data()

        self.assertEqual(result, 2)
        input_mock.assert_not_called()

    def test_production_reset_command_refuses_sqlite_database(self) -> None:
        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        with (
            patch.dict(os.environ, {"FUEL_ENV": "production"}, clear=True),
            patch("backend.app.cli.engine", fake_engine),
            patch("builtins.input") as input_mock,
        ):
            result = reset_production_data()

        self.assertEqual(result, 2)
        input_mock.assert_not_called()

    def _create_verified_meter_photo(
        self,
        session: Session,
        employee: Employee,
        vehicle: Vehicle,
        current_fill: float,
        cumulative_total: float,
        ocr_result: MeterOcrResult | None = None,
        verify: bool = True,
    ) -> MeterPhoto:
        image_buffer = BytesIO()
        self._test_photo_sequence += 1
        image_color = (
            self._test_photo_sequence % 256,
            self._test_photo_sequence * 31 % 256,
            self._test_photo_sequence * 127 % 256,
        )
        Image.new("RGB", (2, 2), color=image_color).save(
            image_buffer, format="PNG"
        )
        with TemporaryDirectory() as upload_directory:
            with (
                patch(
                    "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                    Path(upload_directory),
                ),
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings",
                    return_value=ocr_result
                    or MeterOcrResult(
                            status="ready",
                            provider="tesseract",
                            current_fill_litres=int(
                                Decimal(str(current_fill)) * 1000
                            ),
                            cumulative_total_litres=cumulative_total,
                            current_fill_confidence=99,
                            cumulative_total_confidence=99,
                            current_fill_raw_digits=str(
                                int(Decimal(str(current_fill)) * 1000)
                            ),
                            cumulative_total_raw_digits=str(
                                int(Decimal(str(cumulative_total)) * 1000)
                            ).zfill(6),
                        ),
                ),
            ):
                _, qr_payload = issue_vehicle_qr(session, vehicle.id)
                qr_session = create_qr_session(session, employee, qr_payload)
                self.assertIsNotNone(qr_session)
                session_token, _, _ = qr_session
                photo, _ = store_meter_photo(
                    session,
                    employee,
                    session_token,
                    image_buffer.getvalue(),
                    "image/png",
                )
                self.assertEqual(
                    photo.ocr_status,
                    ocr_result.status if ocr_result is not None else "ready",
                )
                self.assertEqual(
                    photo.ocr_cumulative_total_litres,
                    ocr_result.cumulative_total_litres
                    if ocr_result is not None
                    else cumulative_total,
                )
                if verify:
                    verified = verify_meter_photo(session, employee, photo.id)
                    self.assertIsNotNone(verified)
                    self.assertIsNotNone(verified.verified_at)
                    return verified
                return photo

    def test_sqlite_foreign_keys_are_enabled(self) -> None:
        with self.engine.connect() as connection:
            enabled = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

        self.assertEqual(enabled, 1)

    def test_dashboard_and_inventory_show_unconfigured_without_figures(self) -> None:
        dashboard = get_dashboard_status()
        inventory = get_inventory_status()

        self.assertFalse(dashboard.available)
        self.assertFalse(inventory.available)
        self.assertEqual(inventory.items, [])

    def test_request_session_uses_a_transaction(self) -> None:
        session_generator = get_db_session()
        session = next(session_generator)
        try:
            self.assertTrue(session.in_transaction())
        finally:
            session_generator.close()

    def test_postgresql_database_urls_are_supported(self) -> None:
        engine = create_database_engine("postgresql://localhost/unused")
        try:
            self.assertEqual(engine.url.drivername, "postgresql+psycopg")
        finally:
            engine.dispose()

    def test_migrations_prefer_the_unpooled_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://pooled.example/app",
                "DATABASE_URL_UNPOOLED": "postgresql://direct.example/app",
            },
        ):
            self.assertEqual(get_database_url().host, "pooled.example")
            migration_url = get_migration_database_url()
            self.assertEqual(migration_url.drivername, "postgresql+psycopg")
            self.assertEqual(migration_url.host, "direct.example")

    def test_migrations_fall_back_to_the_database_url(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://pooled.example/app"},
        ):
            with patch.dict(os.environ, {"DATABASE_URL_UNPOOLED": ""}):
                self.assertEqual(
                    get_migration_database_url().host, "pooled.example"
                )

    def test_empty_registry_does_not_authenticate_or_identify(self) -> None:
        with Session(self.engine) as session:
            self.assertIsNone(
                authenticate_employee(session, "nobody@example.test", "some-password")
            )
            self.assertIsNone(identify_vehicle(session, "ABC123"))

    def test_employee_login_and_vehicle_lookup_use_local_registry(self) -> None:
        password = "temporary-test-password"
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session, "worker@example.test", "Test Worker", password
            )
            employee_id = employee.id
            vehicle = create_vehicle(session, "ab12 cde")
            vehicle_data = VehicleRead.model_validate(vehicle).model_dump(by_alias=True)

        with Session(self.engine) as session:
            authenticated = authenticate_employee(
                session, "WORKER@example.test", password
            )
            identified_vehicle = identify_vehicle(session, "AB12 CDE")

        self.assertEqual(authenticated.id, employee_id)
        self.assertEqual(vehicle_data["registrationNumber"], "AB12 CDE")
        self.assertEqual(identified_vehicle.registration_number, "AB12 CDE")

    def test_admin_can_change_employee_role_to_boss(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin = bootstrap_admin(
                session,
                "role-admin@example.test",
                "Role Admin",
                "temporary-admin-password",
            )
            created_boss = add_employee_endpoint(
                EmployeeCreate(
                    email="created-boss@example.com",
                    name="Created Boss",
                    password="temporary-boss-password",
                    role="boss",
                ),
                session,
                admin,
            )
            self.assertEqual(created_boss.role, "boss")
            employee = create_employee(
                session,
                "role-worker@example.com",
                "Role Worker",
                "temporary-worker-password",
            )

            updated = change_employee_role_endpoint(
                employee.id,
                EmployeeRoleUpdate(role="boss"),
                session,
                admin,
            )
            self.assertEqual(updated.role, "boss")
            self.assertEqual(session.get(Employee, employee.id).role, "boss")

            with self.assertRaises(HTTPException) as error:
                change_employee_role_endpoint(
                    admin.id,
                    EmployeeRoleUpdate(role="boss"),
                    session,
                    admin,
                )
            self.assertEqual(error.exception.status_code, 404)

        with self.assertRaises(ValidationError):
            EmployeeRoleUpdate(role="admin")

    def test_admin_can_deactivate_and_reactivate_account_sessions(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin = bootstrap_admin(
                session,
                "status-admin@example.test",
                "Status Admin",
                "temporary-admin-password",
            )
            employee = create_employee(
                session,
                "status-worker@example.com",
                "Status Worker",
                "temporary-worker-password",
            )
            employee_id = employee.id
            token = create_employee_session(session, employee)

            deactivated = change_employee_status_endpoint(
                employee.id,
                EmployeeStatusUpdate.model_validate({"isActive": False}),
                session,
                admin,
            )
            self.assertFalse(deactivated.is_active)
            self.assertIsNone(get_employee_for_session(session, token))
            self.assertIsNotNone(session.get(Employee, employee_id))

            reactivated = change_employee_status_endpoint(
                employee.id,
                EmployeeStatusUpdate.model_validate({"isActive": True}),
                session,
                admin,
            )
            self.assertTrue(reactivated.is_active)
            self.assertIsNone(get_employee_for_session(session, token))

            with self.assertRaises(HTTPException) as error:
                change_employee_status_endpoint(
                    admin.id,
                    EmployeeStatusUpdate(is_active=False),
                    session,
                    admin,
                )
            self.assertEqual(error.exception.status_code, 404)

    def test_admin_can_create_vehicle_with_make_model_and_tank_capacity(self) -> None:
        nct_expiry = date(2027, 10, 5)
        with Session(self.engine) as session, session.begin():
            created_vehicle = add_vehicle_endpoint(
                VehicleCreate(
                    registration_number="ab12 cde",
                    make="Ford",
                    model="Transit",
                    fuel_type="Diesel",
                    tank_capacity=68,
                    nct_expiry_date=nct_expiry,
                ),
                session,
                Employee(role="admin"),
            )
            vehicle_id = created_vehicle.id
            vehicle_data = created_vehicle.model_dump(by_alias=True)
            self.assertEqual(vehicle_data["make"], "Ford")
            self.assertEqual(vehicle_data["model"], "Transit")
            self.assertEqual(vehicle_data["fuelType"], "Diesel")
            self.assertEqual(vehicle_data["tankCapacity"], 68)
            self.assertEqual(vehicle_data["nctExpiryDate"], nct_expiry)

        with Session(self.engine) as session:
            stored_vehicle = session.get(Vehicle, vehicle_id)
            self.assertEqual(stored_vehicle.make, "Ford")
            self.assertEqual(stored_vehicle.model, "Transit")
            self.assertEqual(stored_vehicle.fuel_type, "Diesel")
            self.assertEqual(stored_vehicle.tank_capacity, 68)
            self.assertEqual(stored_vehicle.nct_expiry_date, nct_expiry)

    def test_admin_can_assign_a_shared_vehicle_when_creating_employee(self) -> None:
        admin = Employee(role="admin")
        with Session(self.engine) as session, session.begin():
            available_vehicle = create_vehicle(session, "as12 sig")
            assigned_vehicle = create_vehicle(session, "as34 ned")
            current_employee = create_employee(
                session,
                "current-owner@example.test",
                "Current Owner",
                "temporary-test-password",
            )
            current_employee.vehicles.append(assigned_vehicle)

            created_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="new-worker@example.com",
                    name="New Worker",
                    password="temporary-test-password",
                    vehicle_id=available_vehicle.id,
                ),
                session,
                admin,
            )
            self.assertIn(
                created_employee.id,
                {employee.id for employee in available_vehicle.employees},
            )
            self.assertEqual(
                VehicleRead.model_validate(available_vehicle).model_dump(
                    by_alias=True
                )["employeeCount"],
                1,
            )
            unassigned_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="unassigned-worker@example.com",
                    name="Unassigned Worker",
                    password="temporary-test-password",
                ),
                session,
                admin,
            )
            self.assertIsNone(unassigned_employee.assigned_vehicle)

            shared_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="another-worker@example.com",
                    name="Another Worker",
                    password="temporary-test-password",
                    vehicle_id=assigned_vehicle.id,
                ),
                session,
                admin,
            )
            self.assertEqual(
                {employee.id for employee in assigned_vehicle.employees},
                {current_employee.id, shared_employee.id},
            )

            with self.assertRaises(HTTPException) as missing_error:
                add_employee_endpoint(
                    EmployeeCreate(
                        email="missing-vehicle@example.com",
                        name="Missing Vehicle",
                        password="temporary-test-password",
                        vehicle_id=9999,
                    ),
                    session,
                    admin,
                )
            self.assertEqual(missing_error.exception.status_code, 404)

    def test_two_employees_can_share_vehicle_and_access_only_their_assignment(self) -> None:
        admin = Employee(role="admin")
        with Session(self.engine) as session, session.begin():
            vehicle = create_vehicle(session, "sh12 car")
            first_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="first-shared@example.com",
                    name="First Shared",
                    password="temporary-test-password",
                    vehicle_id=vehicle.id,
                ),
                session,
                admin,
            )
            second_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="second-shared@example.com",
                    name="Second Shared",
                    password="temporary-test-password",
                    vehicle_id=vehicle.id,
                ),
                session,
                admin,
            )
            unassigned_employee = create_employee(
                session,
                "unassigned@example.com",
                "Unassigned",
                "temporary-test-password",
            )

            assigned_vehicle = session.get(Vehicle, vehicle.id)
            self.assertEqual(
                {employee.id for employee in assigned_vehicle.employees},
                {first_employee.id, second_employee.id},
            )
            self.assertEqual(
                VehicleRead.model_validate(assigned_vehicle).employee_count,
                2,
            )
            self.assertEqual(
                my_vehicle(session=session, employee=first_employee).id,
                vehicle.id,
            )
            self.assertEqual(
                my_vehicle(session=session, employee=second_employee).id,
                vehicle.id,
            )
            self.assertIsNone(
                my_vehicle(session=session, employee=unassigned_employee)
            )
            self.assertEqual(
                my_vehicle_fuel_records(
                    session=session, employee=unassigned_employee
                ),
                [],
            )
            self.assertEqual(
                lookup_vehicle(
                    "SH12 CAR", session=session, employee=first_employee
                ).id,
                vehicle.id,
            )
            self.assertEqual(
                lookup_vehicle(
                    "SH12 CAR", session=session, employee=second_employee
                ).id,
                vehicle.id,
            )
            with self.assertRaises(HTTPException) as unavailable_error:
                lookup_vehicle(
                    "SH12 CAR", session=session, employee=unassigned_employee
                )
            self.assertEqual(unavailable_error.exception.status_code, 404)

    def test_inactive_vehicle_cannot_be_assigned_to_new_employee(self) -> None:
        admin = Employee(role="admin")
        with Session(self.engine) as session, session.begin():
            vehicle = create_vehicle(session, "in12 act")
            vehicle_id = vehicle.id
            vehicle.is_active = False

        with self.assertRaises(HTTPException) as inactive_error:
            with Session(self.engine) as session, session.begin():
                add_employee_endpoint(
                    EmployeeCreate(
                        email="inactive-vehicle@example.com",
                        name="Inactive Vehicle",
                        password="temporary-test-password",
                        vehicle_id=vehicle_id,
                    ),
                    session,
                    admin,
                )

        self.assertEqual(inactive_error.exception.status_code, 404)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.scalar(
                    select(Employee).where(
                        Employee.email == "inactive-vehicle@example.com"
                    )
                )
            )

    def test_duplicate_employee_email_does_not_change_vehicle_assignment(self) -> None:
        admin = Employee(role="admin")
        with Session(self.engine) as session, session.begin():
            vehicle = create_vehicle(session, "du12 emp")
            original_employee = create_employee(
                session,
                "existing@example.com",
                "Existing Employee",
                "temporary-test-password",
            )
            original_employee.vehicles.append(vehicle)
            vehicle_id = vehicle.id
            original_employee_id = original_employee.id

        with self.assertRaises(HTTPException) as duplicate_error:
            with Session(self.engine) as session, session.begin():
                add_employee_endpoint(
                    EmployeeCreate(
                        email="EXISTING@example.com",
                        name="Duplicate Employee",
                        password="temporary-test-password",
                        vehicle_id=vehicle_id,
                    ),
                    session,
                    admin,
                )

        self.assertEqual(duplicate_error.exception.status_code, 409)
        with Session(self.engine) as session:
            stored_vehicle = session.get(Vehicle, vehicle_id)
            self.assertEqual(
                [employee.id for employee in stored_vehicle.employees],
                [original_employee_id],
            )
            self.assertEqual(
                session.scalar(
                    select(Employee.id).where(Employee.email == "existing@example.com")
                ),
                original_employee_id,
            )

    def test_employee_vehicle_assignment_rejects_conflicting_or_invalid_input(self) -> None:
        base_payload = {
            "email": "invalid-assignment@example.com",
            "name": "Invalid Assignment",
            "password": "temporary-test-password",
        }
        invalid_assignments = (
            {"vehicle_id": 0},
            {"vehicle_id": 1, "vehicle_registration_number": "AB12 CDE"},
            {"vehicle_make": "Ford"},
            {"vehicle_fuel_type": "LPG"},
            {"vehicle_registration_number": "AB12 CDE", "vehicle_tank_capacity": 0},
        )

        for assignment in invalid_assignments:
            with self.subTest(assignment=assignment):
                with self.assertRaises(ValidationError):
                    EmployeeCreate(**base_payload, **assignment)

        with self.assertRaises(ValidationError):
            VehicleCreate(registration_number="AB12 CDE", fuel_type="LPG")

    def test_admin_can_create_employee_with_vehicle_registration_and_nct(self) -> None:
        admin = Employee(role="admin")
        nct_expiry = date(2027, 10, 5)
        with Session(self.engine) as session, session.begin():
            created_employee = add_employee_endpoint(
                EmployeeCreate(
                    email="new-owner@example.com",
                    name="New Owner",
                    password="temporary-test-password",
                    vehicle_registration_number="ab12 cde",
                    vehicle_make="Ford",
                    vehicle_model="Transit",
                    vehicle_fuel_type="Diesel",
                    vehicle_tank_capacity=68,
                    nct_expiry_date=nct_expiry,
                ),
                session,
                admin,
            )
            assigned_vehicle = created_employee.assigned_vehicle
            self.assertIsNotNone(assigned_vehicle)
            self.assertEqual(assigned_vehicle.registration_number, "AB12 CDE")
            self.assertEqual(assigned_vehicle.employee_count, 1)
            self.assertEqual(assigned_vehicle.make, "Ford")
            self.assertEqual(assigned_vehicle.model, "Transit")
            self.assertEqual(assigned_vehicle.fuel_type, "Diesel")
            self.assertEqual(assigned_vehicle.tank_capacity, 68)
            assigned_vehicle_id = assigned_vehicle.id
            created_employee_id = created_employee.id
            self.assertEqual(
                created_employee.model_dump(by_alias=True)["assignedVehicle"][
                    "registrationNumber"
                ],
                "AB12 CDE",
            )

        with Session(self.engine) as session:
            stored_vehicle = session.get(Vehicle, assigned_vehicle_id)
            self.assertIsNotNone(stored_vehicle)
            self.assertEqual(
                [employee.id for employee in stored_vehicle.employees],
                [created_employee_id],
            )
            self.assertEqual(stored_vehicle.make, "Ford")
            self.assertEqual(stored_vehicle.model, "Transit")
            self.assertEqual(stored_vehicle.tank_capacity, 68)
            self.assertEqual(stored_vehicle.nct_expiry_date, nct_expiry)

        with Session(self.engine) as session, session.begin():
            duplicate_vehicle = create_vehicle(session, "dp12 reg")
            duplicate_vehicle_id = duplicate_vehicle.id
        with self.assertRaises(HTTPException) as duplicate_error:
            with Session(self.engine) as session, session.begin():
                add_employee_endpoint(
                    EmployeeCreate(
                        email="duplicate-owner@example.com",
                        name="Duplicate Owner",
                        password="temporary-test-password",
                        vehicle_registration_number="DP12 REG",
                    ),
                    session,
                    admin,
                )
        self.assertEqual(duplicate_error.exception.status_code, 409)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.scalar(
                    select(Employee).where(
                        Employee.username == "duplicate-owner@example.com"
                    )
                )
            )
            self.assertEqual(
                session.scalar(
                    select(Vehicle).where(Vehicle.id == duplicate_vehicle_id)
                ).registration_number,
                "DP12 REG",
            )

    def test_qr_session_photo_is_private_vehicle_bound_and_one_use(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_buffer, format="PNG")
        image_data = image_buffer.getvalue()
        with TemporaryDirectory() as upload_directory:
            with patch(
                "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                Path(upload_directory),
            ):
                with Session(self.engine) as session, session.begin():
                    employee = create_employee(
                        session,
                        "worker@example.test",
                        "Test Worker",
                        "temporary-password",
                    )
                    other_employee = create_employee(
                        session,
                        "other@example.test",
                        "Other Worker",
                        "temporary-password",
                    )
                    vehicle = create_vehicle(session, "ab12 cde")
                    employee.vehicles.append(vehicle)
                    other_employee.vehicles.append(vehicle)
                    _, qr_payload = issue_vehicle_qr(session, vehicle.id)
                    qr_session = create_qr_session(session, employee, qr_payload)
                    self.assertIsNotNone(qr_session)
                    shared_employee_session = create_qr_session(
                        session, other_employee, qr_payload
                    )
                    self.assertIsNotNone(shared_employee_session)
                    outsider = create_employee(
                        session,
                        "outsider@example.test",
                        "Outsider",
                        "temporary-password",
                    )
                    self.assertIsNone(create_qr_session(session, outsider, qr_payload))
                    session_token, registration, _ = qr_session
                    self.assertEqual(registration, "AB12 CDE")

                    expired_session = get_qr_session_by_hash(
                        session,
                        sha256(session_token.encode("utf-8")).hexdigest(),
                    )
                    expired_session.expires_at = datetime.now(timezone.utc) - timedelta(
                        seconds=1
                    )
                    with self.assertRaises(InvalidQrSession):
                        store_meter_photo(
                            session,
                            employee,
                            session_token,
                            image_data,
                            "image/png",
                        )
                    qr_session = create_qr_session(session, employee, qr_payload)
                    self.assertIsNotNone(qr_session)
                    session_token, registration, _ = qr_session
                    self.assertEqual(registration, "AB12 CDE")
                    with self.assertRaises(InvalidQrSession):
                        store_meter_photo(
                            session,
                            other_employee,
                            session_token,
                            image_data,
                            "image/png",
                        )

                    with patch(
                        "backend.app.services.meter_photos.extract_meter_readings",
                        return_value=MeterOcrResult(status="unavailable"),
                    ):
                        stored_photo, stored_registration = store_meter_photo(
                            session,
                            employee,
                            session_token,
                            image_data,
                            "image/png",
                        )
                    stored_path = Path(upload_directory) / stored_photo.storage_key
                    self.assertEqual(stored_registration, "AB12 CDE")
                    self.assertTrue(stored_path.is_file())
                    self.assertEqual(stored_path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(stored_photo.sha256, sha256(image_data).hexdigest())
                    with self.assertRaises(InvalidQrSession):
                        store_meter_photo(
                            session,
                            employee,
                            session_token,
                            image_data,
                            "image/png",
                        )

    def test_meter_photo_retrieval_is_limited_to_owner_or_management(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_buffer, format="PNG")
        image_data = image_buffer.getvalue()
        with TemporaryDirectory() as upload_directory:
            with (
                patch(
                    "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                    Path(upload_directory),
                ),
                patch(
                    "backend.app.services.meter_photos.extract_meter_readings",
                    return_value=MeterOcrResult(status="unavailable"),
                ),
                Session(self.engine) as session,
                session.begin(),
            ):
                employee = create_employee(
                    session,
                    "photo-owner@example.test",
                    "Photo Owner",
                    "temporary-password",
                )
                outsider = create_employee(
                    session,
                    "photo-outsider@example.test",
                    "Photo Outsider",
                    "temporary-password",
                )
                vehicle = create_vehicle(session, "ph12 oto")
                employee.vehicles.append(vehicle)
                photo_session = create_assigned_vehicle_photo_session(
                    session, employee
                )
                self.assertIsNotNone(photo_session)
                meter_photo, _ = store_meter_photo(
                    session,
                    employee,
                    photo_session[0],
                    image_data,
                    "image/png",
                )

                response = read_meter_photo_content_endpoint(
                    meter_photo.id,
                    session,
                    employee,
                )
                self.assertEqual(response.body, image_data)
                with self.assertRaises(HTTPException) as error:
                    read_meter_photo_content_endpoint(
                        meter_photo.id,
                        session,
                        outsider,
                    )
                self.assertEqual(error.exception.status_code, 404)

    def test_assigned_vehicle_photo_session_uses_only_employee_vehicle(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "worker@example.test",
                "Test Worker",
                "temporary-password",
            )
            other_employee = create_employee(
                session,
                "other@example.test",
                "Other Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "ab12 cde")
            employee.vehicles.append(vehicle)
            other_vehicle = create_vehicle(session, "xy34 zzz")
            other_employee.vehicles.append(other_vehicle)

            created = create_assigned_vehicle_photo_session(session, employee)
            self.assertIsNotNone(created)
            session_token, registration_number, expires_at = created
            photo_session = get_qr_session_by_hash(
                session, sha256(session_token.encode("utf-8")).hexdigest()
            )

            self.assertEqual(registration_number, vehicle.registration_number)
            self.assertEqual(photo_session.employee_id, employee.id)
            self.assertEqual(photo_session.vehicle_id, vehicle.id)
            self.assertGreater(expires_at, datetime.now(timezone.utc))
            other_session = create_assigned_vehicle_photo_session(
                session, other_employee
            )
            self.assertIsNotNone(other_session)
            self.assertEqual(other_session[1], other_vehicle.registration_number)

            unassigned_employee = create_employee(
                session,
                "unassigned@example.test",
                "Unassigned Worker",
                "temporary-password",
            )
            self.assertIsNone(
                create_assigned_vehicle_photo_session(session, unassigned_employee)
            )

    def test_meter_photo_validation_rejects_unsupported_and_invalid_images(self) -> None:
        with self.assertRaises(UnsupportedMeterPhotoType):
            validate_meter_photo(b"not an image", "image/gif")
        with self.assertRaises(ValueError):
            validate_meter_photo(b"not an image", "image/jpeg")

    def test_tesseract_parser_uses_first_line_for_fill_and_second_for_total(self) -> None:
        result = parse_meter_ocr_data(
            {
                "text": ["5.00", "9667.50"],
                "conf": ["96", "94"],
                "top": ["100", "140"],
                "block_num": ["1", "1"],
                "par_num": ["1", "1"],
                "line_num": ["1", "2"],
            }
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.current_fill_litres, 500)
        self.assertEqual(result.cumulative_total_litres, 966.75)
        self.assertNotEqual(
            result.current_fill_litres,
            result.cumulative_total_litres,
        )

    def test_tesseract_parser_reads_labeled_two_line_values(self) -> None:
        result = parse_meter_ocr_data(
            {
                "text": ["CURRENT", "FILL:", "8.25", "TOTAL:", "1340.75"],
                "conf": ["91", "90", "96", "93", "95"],
                "top": ["80", "80", "80", "145", "145"],
                "block_num": ["1", "1", "1", "1", "1"],
                "par_num": ["1", "1", "1", "1", "1"],
                "line_num": ["1", "1", "1", "2", "2"],
            }
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.current_fill_litres, 825)
        self.assertEqual(result.cumulative_total_litres, 134.075)

    def test_low_confidence_or_missing_second_reading_is_uncertain(self) -> None:
        low_confidence = parse_meter_ocr_data(
            {
                "text": ["8.25", "1340.75"],
                "conf": ["22", "94"],
                "top": ["100", "140"],
                "block_num": ["1", "1"],
                "par_num": ["1", "1"],
                "line_num": ["1", "2"],
            }
        )
        missing_second_reading = parse_meter_ocr_data(
            {
                "text": ["8.25"],
                "conf": ["96"],
                "top": ["100"],
                "block_num": ["1"],
                "par_num": ["1"],
                "line_num": ["1"],
            }
        )
        zero_fill = parse_meter_ocr_data(
            {
                "text": ["0.00", "1340.75"],
                "conf": ["96", "94"],
                "top": ["100", "140"],
                "block_num": ["1", "1"],
                "par_num": ["1", "1"],
                "line_num": ["1", "2"],
            }
        )

        self.assertEqual(low_confidence.status, "uncertain")
        self.assertEqual(missing_second_reading.status, "uncertain")
        self.assertEqual(zero_fill.status, "uncertain")
        self.assertIsNotNone(low_confidence.message)
        self.assertIsNotNone(missing_second_reading.message)

    def test_missing_local_tesseract_is_reported_without_auto_acceptance(self) -> None:
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (32, 32), color="white").save(image_buffer, format="PNG")
        with patch(
            "pytesseract.image_to_data",
            side_effect=pytesseract.pytesseract.TesseractNotFoundError(),
        ):
            result = extract_meter_readings(image_buffer.getvalue())

        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.current_fill_litres)
        self.assertIsNone(result.cumulative_total_litres)
        self.assertIn("Tesseract executable", result.message)

    def test_tesseract_uses_macports_binary_when_it_is_not_on_path(self) -> None:
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (32, 32), color="white").save(image_buffer, format="PNG")
        ocr_data = {
            "text": ["5.00", "9667.50"],
            "conf": ["96", "94"],
            "top": ["100", "140"],
            "block_num": ["1", "1"],
            "par_num": ["1", "1"],
            "line_num": ["1", "2"],
        }
        with (
            patch.object(pytesseract.pytesseract, "tesseract_cmd", "tesseract"),
            patch(
                "backend.app.services.meter_ocr.shutil.which",
                return_value=None,
            ),
            patch(
                "backend.app.services.meter_ocr.os.access",
                side_effect=lambda path, mode: path == "/opt/local/bin/tesseract",
            ),
            patch("pytesseract.image_to_data", return_value=ocr_data),
        ):
            result = extract_meter_readings(image_buffer.getvalue())

            self.assertEqual(
                pytesseract.pytesseract.tesseract_cmd,
                "/opt/local/bin/tesseract",
            )

        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.current_fill_litres)
        self.assertIsNone(result.cumulative_total_litres)

    def test_tesseract_detects_standard_windows_install_path(self) -> None:
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (32, 32), color="white").save(image_buffer, format="PNG")
        ocr_data = {
            "text": ["5.00", "9667.50"],
            "conf": ["96", "94"],
            "top": ["10", "20"],
            "block_num": ["1", "1"],
            "par_num": ["1", "1"],
            "line_num": ["1", "2"],
        }
        windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        with (
            patch.dict(os.environ, {"TESSERACT_CMD": ""}),
            patch.object(pytesseract.pytesseract, "tesseract_cmd", "tesseract"),
            patch(
                "backend.app.services.meter_ocr.shutil.which",
                return_value=None,
            ),
            patch(
                "backend.app.services.meter_ocr.os.access",
                side_effect=lambda path, mode: path == windows_path,
            ),
            patch("pytesseract.image_to_data", return_value=ocr_data),
        ):
            result = extract_meter_readings(image_buffer.getvalue())
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, windows_path)

        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.current_fill_litres)
        self.assertIsNone(result.cumulative_total_litres)

    def test_tesseract_retries_center_crop_with_digit_whitelist(self) -> None:
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (1000, 1000), color="white").save(
            image_buffer, format="PNG"
        )
        readings = {
            "text": ["12.5", "261563.0"],
            "conf": ["96", "94"],
            "top": ["100", "300"],
            "block_num": ["1", "1"],
            "par_num": ["1", "1"],
            "line_num": ["1", "2"],
        }
        with (
            patch.dict(os.environ, {"TESSERACT_CMD": ""}),
            patch(
                "pytesseract.image_to_data",
                side_effect=[{}, {}, {}, {}, readings],
            ) as image_to_data,
        ):
            result = extract_meter_readings(image_buffer.getvalue())

        calls = image_to_data.call_args_list
        self.assertEqual(calls[0].args[0].size, (1600, 1600))
        self.assertEqual(calls[4].args[0].size, (1600, 819))
        self.assertIn("tessedit_char_whitelist", calls[1].kwargs["config"])
        self.assertEqual(result.status, "uncertain")
        self.assertIsNone(result.current_fill_litres)
        self.assertIsNone(result.cumulative_total_litres)

    def test_tesseract_failure_is_reported_without_auto_acceptance(self) -> None:
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (32, 32), color="white").save(image_buffer, format="PNG")
        with patch(
            "pytesseract.image_to_data",
            side_effect=pytesseract.pytesseract.TesseractError(1, "OCR failed"),
        ):
            result = extract_meter_readings(image_buffer.getvalue())

        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.current_fill_litres)
        self.assertIn("OCR failed", result.message)

    def test_google_vision_uses_document_ocr_and_parses_ordered_readings(self) -> None:
        def vision_word(text: str, x: int, y: int, confidence: float) -> dict:
            return {
                "symbols": [{"text": character} for character in text],
                "boundingBox": {
                    "vertices": [
                        {"x": x, "y": y},
                        {"x": x + 20, "y": y},
                        {"x": x + 20, "y": y + 20},
                        {"x": x, "y": y + 20},
                    ]
                },
                "confidence": confidence,
            }

        def vision_document(words: list[dict]) -> dict:
            return {
                "pages": [
                    {
                        "blocks": [
                            {
                                "paragraphs": [
                                    {"words": words}
                                ]
                            }
                        ]
                    }
                ]
            }

        google_response = {
            "responses": [
                {
                    "fullTextAnnotation": vision_document(
                        [
                            vision_word("22032", 10, 100, 0.94),
                            vision_word("26.56", 10, 150, 0.96),
                        ]
                    )
                },
                {
                    "fullTextAnnotation": vision_document(
                        []
                    )
                },
                {
                    "fullTextAnnotation": vision_document(
                        [
                            vision_word("26", 10, 50, 0.96),
                            vision_word("1563", 40, 50, 0.96),
                        ]
                    )
                },
            ]
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            google_response
        ).encode()
        image = BytesIO()
        Image.new("RGB", (768, 1024), "white").save(image, format="JPEG")
        with (
            patch.dict(
                os.environ,
                {
                    "FUEL_OCR_PROVIDER": "google_vision",
                    "GOOGLE_CLOUD_VISION_API_KEY": "test-key",
                },
            ),
            patch(
                "backend.app.services.meter_ocr.urlopen",
                return_value=response,
            ) as urlopen_mock,
        ):
            result = _extract_google_vision_readings(
                image.getvalue(), "test-key"
            )

        request = urlopen_mock.call_args.args[0]
        request_payload = json.loads(request.data)
        self.assertEqual(request.method, "POST")
        self.assertEqual(parse_qs(urlparse(request.full_url).query), {"key": ["test-key"]})
        self.assertEqual(len(request_payload["requests"]), 3)
        self.assertEqual(
            request_payload["requests"][0]["features"],
            [
                {"type": "TEXT_DETECTION"},
                {"type": "DOCUMENT_TEXT_DETECTION"},
            ],
        )
        prepared_image = Image.open(
            BytesIO(
                base64.b64decode(
                    request_payload["requests"][0]["image"]["content"]
                )
            )
        )
        self.assertEqual(prepared_image.width, 1200)
        self.assertLess(prepared_image.height, 1024)
        current_row_image = Image.open(
            BytesIO(
                base64.b64decode(
                    request_payload["requests"][1]["image"]["content"]
                )
            )
        )
        self.assertEqual(current_row_image.width, 1600)
        self.assertLess(current_row_image.height, prepared_image.height)
        total_row_image = Image.open(
            BytesIO(
                base64.b64decode(
                    request_payload["requests"][2]["image"]["content"]
                )
            )
        )
        self.assertEqual(total_row_image.width, 1600)
        self.assertLess(total_row_image.height, prepared_image.height)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.current_fill_raw_digits, "22032")
        self.assertEqual(result.cumulative_total_raw_digits, "261563")
        self.assertIsNone(result.current_fill_decimal_position)
        self.assertIsNone(result.cumulative_total_decimal_position)
        self.assertEqual(result.current_fill_confidence, 94.0)
        self.assertEqual(result.cumulative_total_confidence, 96.0)

        def read_with_total_candidates(
            display_total: str,
            close_total: str,
            confidence: float,
        ) -> MeterOcrResult:
            response_data = {
                "responses": [
                    {
                        "fullTextAnnotation": vision_document(
                            [
                                vision_word("22032", 10, 100, 0.96),
                                vision_word(display_total, 10, 150, 0.96),
                            ]
                        )
                    },
                    {"fullTextAnnotation": vision_document([])},
                    {
                        "fullTextAnnotation": vision_document(
                            [vision_word(close_total, 10, 50, confidence)]
                        )
                    },
                ]
            }
            variant_response = MagicMock()
            variant_response.__enter__.return_value.read.return_value = json.dumps(
                response_data
            ).encode()
            detected_response = MagicMock()
            detected_response.__enter__.return_value.read.return_value = json.dumps(
                {
                    "responses": [
                        {
                            "fullTextAnnotation": vision_document(
                                [
                                    vision_word("26", 10, 50, 0.96),
                                    vision_word("1563", 40, 50, 0.96),
                                ]
                            )
                        }
                    ]
                }
            ).encode()
            with (
                patch.dict(
                    os.environ,
                    {
                        "FUEL_OCR_PROVIDER": "google_vision",
                        "GOOGLE_CLOUD_VISION_API_KEY": "test-key",
                    },
                ),
                patch(
                    "backend.app.services.meter_ocr.urlopen",
                    side_effect=[variant_response, detected_response],
                ),
            ):
                return _extract_google_vision_readings(
                    image.getvalue(), "test-key"
                )

        disagreeing_total = read_with_total_candidates(
            "261563",
            "2615631",
            0.96,
        )
        self.assertEqual(disagreeing_total.status, "uncertain")
        self.assertIn("different PIUSI TOTAL values", disagreeing_total.message)

        low_confidence_total = read_with_total_candidates(
            "26.56",
            "2615631",
            0.65,
        )
        self.assertEqual(low_confidence_total.status, "uncertain")
        self.assertEqual(low_confidence_total.cumulative_total_raw_digits, "261563")
        self.assertEqual(low_confidence_total.cumulative_total_confidence, 96.0)

    def test_google_vision_requires_key_and_reports_api_errors(self) -> None:
        image = BytesIO()
        Image.new("RGB", (768, 1024), "white").save(image, format="JPEG")
        image_content = image.getvalue()
        with patch.dict(
            os.environ,
            {"FUEL_OCR_PROVIDER": "google_vision"},
            clear=True,
        ):
            missing_key = extract_meter_readings(image_content)

        self.assertEqual(missing_key.status, "unavailable")
        self.assertIn("GOOGLE_CLOUD_VISION_API_KEY", missing_key.message)

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "responses": [
                    {"error": {"message": "API key invalid"}},
                    {},
                    {},
                ]
            }
        ).encode()
        with (
            patch.dict(
                os.environ,
                {
                    "FUEL_OCR_PROVIDER": "google_vision",
                    "GOOGLE_CLOUD_VISION_API_KEY": "test-key",
                },
            ),
            patch(
                "backend.app.services.meter_ocr.urlopen",
                return_value=response,
            ),
        ):
            api_error = extract_meter_readings(image_content)

        self.assertEqual(api_error.status, "failed")
        self.assertIn("API key invalid", api_error.message)

    def test_production_defaults_to_google_vision(self) -> None:
        with patch.dict(
            os.environ,
            {"FUEL_ENV": "production", "GOOGLE_CLOUD_VISION_API_KEY": ""},
            clear=True,
        ):
            result = extract_meter_readings(b"test-image")

        self.assertEqual(result.status, "unavailable")
        self.assertIn("Google Vision is selected", result.message)

    def test_local_defaults_to_google_vision_when_key_is_configured(self) -> None:
        expected = MeterOcrResult(
            status="ready",
            current_fill_litres=125,
            cumulative_total_litres=261.563,
            current_fill_confidence=99,
            cumulative_total_confidence=99,
        )
        with (
            patch.dict(
                os.environ,
                {
                    "FUEL_ENV": "development",
                    "GOOGLE_CLOUD_VISION_API_KEY": "test-key",
                },
                clear=True,
            ),
            patch(
                "backend.app.services.meter_ocr._extract_google_vision_readings",
                return_value=expected,
            ) as vision_mock,
            patch(
                "backend.app.services.meter_ocr.recognize_piusi_lcd",
                return_value=object(),
            ) as lcd_mock,
            patch(
                "backend.app.services.meter_ocr._apply_piusi_evidence",
                side_effect=lambda result, _lcd, _provider: result,
            ),
            patch(
                "backend.app.services.meter_ocr._extract_tesseract_readings"
            ) as tesseract_mock,
        ):
            result = extract_meter_readings(b"meter image")

        self.assertEqual(result, expected)
        vision_mock.assert_called_once_with(
            b"meter image", "test-key", lcd_mock.return_value
        )
        tesseract_mock.assert_not_called()

    def test_local_defaults_to_tesseract_without_google_vision_key(self) -> None:
        expected = MeterOcrResult(status="uncertain")
        with (
            patch.dict(
                os.environ,
                {"FUEL_ENV": "development"},
                clear=True,
            ),
            patch(
                "backend.app.services.meter_ocr._extract_google_vision_readings"
            ) as vision_mock,
            patch(
                "backend.app.services.meter_ocr._extract_tesseract_readings",
                return_value=expected,
            ) as tesseract_mock,
            patch(
                "backend.app.services.meter_ocr.recognize_piusi_lcd",
                return_value=object(),
            ) as lcd_mock,
            patch(
                "backend.app.services.meter_ocr._apply_piusi_evidence",
                side_effect=lambda result, _lcd, _provider: result,
            ),
        ):
            result = extract_meter_readings(b"meter image")

        self.assertEqual(result, expected)
        tesseract_mock.assert_called_once_with(b"meter image")
        self.assertEqual(lcd_mock.call_count, 1)
        vision_mock.assert_not_called()

    def test_fuel_submission_uses_fill_and_compares_cumulative_reading(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session, "meter@example.test", "Meter Worker", "temporary-password"
            )
            vehicle = create_vehicle(session, "me12 ter")
            employee.vehicles.append(vehicle)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=90,
                    current_total_integer=90_000,
                    current_total_raw_digits="90000",
                    revision=1,
                )
            )

            first_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 10.0, 100.0
            )
            first_record = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=first_photo.id,
                    odometer_miles=1000,
                ),
            )
            with self.assertRaises(FuelSubmissionError):
                save_fuel_record(
                    session,
                    employee,
                    FuelRecordCreate(
                        meter_photo_id=first_photo.id,
                        odometer_miles=1000,
                    ),
                )
            second_photo = self._create_verified_meter_photo(
                    session, employee, vehicle, 5.0, 105.0
            )
            with patch.dict(os.environ, {"FUEL_METER_TOLERANCE_LITRES": "0.10"}):
                second_record = save_fuel_record(
                    session,
                    employee,
                    FuelRecordCreate(
                        meter_photo_id=second_photo.id,
                        odometer_miles=1100,
                    ),
                )
            first_values = (
                first_record.litres,
                first_record.current_fill_litres,
                first_record.cumulative_total_litres,
                first_record.meter_check_status,
            )
            second_values = (
                second_record.litres,
                second_record.current_fill_litres,
                second_record.cumulative_total_litres,
                second_record.meter_delta_litres,
                second_record.meter_check_status,
            )
            response_data = FuelRecordRead.model_validate(
                second_record
            ).model_dump(by_alias=True)

        self.assertEqual(first_values, (10.0, 10.0, 100.0, "matched"))
        self.assertEqual(second_values[:3], (5.0, 5.0, 105.0))
        self.assertEqual(second_values[3], 5.0)
        self.assertEqual(second_values[4], "matched")
        self.assertEqual(response_data["currentFillLitres"], 5.0)
        self.assertEqual(response_data["cumulativeTotalLitres"], 105.0)
        self.assertEqual(response_data["mileageMiles"], 1100.0)
        self.assertEqual(response_data["currentOdometerMiles"], 1100.0)

    def test_manual_fuel_submission_saves_readings_without_a_photo(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "manual-fill@example.test",
                "Manual Fill Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "ma12 nual")
            employee.vehicles.append(vehicle)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=90,
                    current_total_integer=90_000,
                    current_total_raw_digits="90000",
                    revision=1,
                )
            )

            request = FuelRecordCreate.model_validate(
                {
                    "cumulativeTotalLitres": "100",
                    "confirmed": True,
                    "calculatedFillConfirmed": True,
                    "odometerMiles": 1000,
                }
            )
            record = save_fuel_record(session, employee, request)
            response_data = FuelRecordRead.model_validate(
                record
            ).model_dump(by_alias=True)
            meter_state = get_or_create_global_meter_state(session)
            record_values = (
                record.meter_photo_id,
                record.litres,
                record.current_fill_litres,
                record.cumulative_total_litres,
                record.meter_check_status,
                meter_state.current_cumulative_total_litres,
            )

        self.assertEqual(
            record_values,
            (None, 10.0, 10.0, 100.0, "matched", 100.0),
        )
        self.assertIsNone(response_data["meterPhotoId"])

    def test_manual_fuel_submission_requires_confirmation_and_precise_values(
        self,
    ) -> None:
        for readings in (
            {
                "cumulative_total_litres": Decimal("100"),
                "confirmed": False,
            },
            {"cumulative_total_litres": Decimal("100.1234"), "confirmed": True},
            {
                "cumulative_total_litres": Decimal("100"),
                "cumulative_total_raw_digits": "100000",
                "confirmed": True,
            },
            {
                "cumulative_total_raw_digits": "26156",
                "confirmed": True,
            },
            {
                "cumulative_total_raw_digits": "2615630",
                "confirmed": True,
            },
        ):
            with self.subTest(readings=readings):
                with self.assertRaises(ValidationError):
                    FuelRecordCreate(odometer_miles=1000, **readings)

    def test_boss_can_find_and_record_a_fill_for_another_registered_vehicle(
        self,
    ) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_buffer, format="PNG")

        with Session(self.engine) as session, session.begin():
            boss = create_employee(
                session,
                "fleet-boss@example.test",
                "Fleet Boss",
                "temporary-password",
                role="boss",
            )
            assigned_driver = create_employee(
                session,
                "fleet-driver@example.test",
                "Fleet Driver",
                "temporary-password",
            )
            other_driver = create_employee(
                session,
                "other-driver@example.test",
                "Other Driver",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "AB12 CDE")
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 80
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=0,
                    current_total_integer=0,
                    current_total_raw_digits="0",
                    revision=1,
                )
            )
            assigned_driver.vehicles.append(vehicle)
            other_vehicle = create_vehicle(session, "XY34 ZZZ")
            other_vehicle.fuel_type = "Diesel"
            other_vehicle.tank_capacity = 60
            other_driver.vehicles.append(other_vehicle)

            found_vehicle = lookup_vehicle(
                "ab12 cde", session=session, employee=boss
            )
            self.assertEqual(found_vehicle.id, vehicle.id)
            self.assertEqual(found_vehicle.registration_number, "AB12 CDE")

            created_session = start_vehicle_photo_session_endpoint(
                Response(),
                session,
                boss,
                MeterPhotoSessionCreate(vehicle_id=found_vehicle.id),
            )
            session_token = created_session.session_token
            self.assertEqual(
                created_session.registration_number, vehicle.registration_number
            )

            with TemporaryDirectory() as upload_directory:
                with (
                    patch(
                        "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                        Path(upload_directory),
                    ),
                    patch(
                        "backend.app.services.meter_photos.extract_meter_readings",
                        return_value=MeterOcrResult(
                            status="ready",
                            provider="tesseract",
                            current_fill_litres=10000,
                            cumulative_total_litres=10,
                            current_fill_confidence=99,
                            cumulative_total_confidence=99,
                            current_fill_raw_digits="10000",
                            cumulative_total_raw_digits="010000",
                        ),
                    ),
                ):
                    photo, _ = store_meter_photo(
                        session,
                        boss,
                        session_token,
                        image_buffer.getvalue(),
                        "image/png",
                    )

            verified_photo = verify_meter_photo(session, boss, photo.id)
            self.assertIsNotNone(verified_photo)
            record = save_fuel_record(
                session,
                boss,
                FuelRecordCreate(
                    meter_photo_id=photo.id,
                    odometer_miles=1000,
                    vehicle_id=vehicle.id,
                ),
            )
            self.assertEqual(record.vehicle_id, vehicle.id)
            self.assertEqual(record.reg_number, "AB12 CDE")

            with self.assertRaises(MeterPhotoNotOwned):
                save_fuel_record(
                    session,
                    boss,
                    FuelRecordCreate(
                        meter_photo_id=photo.id,
                        odometer_miles=1000,
                        vehicle_id=other_vehicle.id,
                    ),
                )
            self.assertIsNone(
                create_vehicle_photo_session(session, other_driver, vehicle.id)
            )
            with self.assertRaisesRegex(FuelSubmissionError, "Only boss accounts"):
                save_fuel_record(
                    session,
                    other_driver,
                    FuelRecordCreate(
                        meter_photo_id=photo.id,
                        odometer_miles=1000,
                        vehicle_id=vehicle.id,
                    ),
                )

    def test_demo_employee_fills_update_the_global_reading_and_history(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)
            emma = session.scalar(
                select(Employee).where(Employee.username == "Tommy1")
            )
            emma2 = session.scalar(
                select(Employee).where(Employee.username == "Tommy2")
            )
            emma_vehicle = session.scalar(
                select(Vehicle).where(
                    Vehicle.registration_number == "DD-TOMMY-001"
                )
            )
            emma2_vehicle = session.scalar(
                select(Vehicle).where(
                    Vehicle.registration_number == "DD-TOMMY-002"
                )
            )
            baseline = get_global_meter_summary(session)
            self.assertEqual(baseline["current_cumulative_total_litres"], 9650.0)
            self.assertEqual(baseline["previous_cumulative_total_litres"], 9375.0)
            meter_state = get_or_create_global_meter_state(session)
            meter_state.current_total_integer = 9_650_000
            meter_state.previous_total_integer = 9_375_000
            meter_state.current_total_raw_digits = "9650000"

            emma_photo = self._create_verified_meter_photo(
                session, emma, emma_vehicle, 5.0, 9655.0
            )
            emma_record = save_fuel_record(
                session,
                emma,
                FuelRecordCreate(
                    meter_photo_id=emma_photo.id,
                    odometer_miles=12885,
                ),
            )
            emma2_photo = self._create_verified_meter_photo(
                session, emma2, emma2_vehicle, 8.0, 9663.0
            )
            emma2_record = save_fuel_record(
                session,
                emma2,
                FuelRecordCreate(
                    meter_photo_id=emma2_photo.id,
                    odometer_miles=13310,
                ),
            )
            state = get_or_create_global_meter_state(session)
            summary = get_global_meter_summary(session)
            history = list_global_meter_history(session, limit=200)
            emma_record_id = emma_record.id
            emma_record_is_demo = emma_record.is_demo
            emma2_record_id = emma2_record.id
            emma2_record_is_demo = emma2_record.is_demo
            emma2_photo_id = emma2_photo.id
            values = (
                state.current_cumulative_total_litres,
                state.previous_cumulative_total_litres,
                state.last_transaction_id,
                state.revision,
            )

        self.assertEqual(values, (9663.0, 9655.0, emma2_record_id, 2))
        self.assertEqual(summary["last_employee_name"], "Tommy2")
        self.assertEqual(summary["last_vehicle_registration"], "DD-TOMMY-002")
        self.assertEqual(summary["last_meter_photo_id"], emma2_photo_id)
        self.assertEqual(history[0]["id"], f"fill-{emma2_record_id}")
        self.assertEqual(history[0]["difference_litres"], 8.0)
        self.assertEqual(history[0]["notes"], f"global-meter-test:Tommy2:{emma2_photo_id}")
        self.assertTrue(emma_record_is_demo)
        self.assertTrue(emma2_record_is_demo)

    def test_global_meter_lower_reading_is_flagged_and_can_be_reviewed(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session, "global-reset@example.test", "Global Reset Worker",
                "temporary-password"
            )
            admin = bootstrap_admin(
                session,
                "global-reset-admin@example.test",
                "Global Reset Admin",
                "temporary-admin-password",
            )
            vehicle = create_vehicle(session, "gr12 eset")
            employee.vehicles.append(vehicle)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=90,
                    current_total_integer=90_000,
                    current_total_raw_digits="90000",
                    revision=1,
                )
            )
            first_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 10.0, 100.0
            )
            first_record = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(meter_photo_id=first_photo.id, odometer_miles=1000),
            )
            lower_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 1.0, 99.0
            )
            self.assertTrue(
                any(
                    "decreased" in warning
                    for warning in lower_photo.reading_warnings
                )
            )
            lower_record = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=lower_photo.id,
                    odometer_miles=1100,
                )
            )
            self.assertIsInstance(lower_record, MeterReadingReview)
            self.assertTrue(lower_record.warnings)
            state = get_or_create_global_meter_state(session)
            self.assertEqual(state.current_total_integer, 100_000)
            rejected = decide_meter_reading_review(
                session,
                admin,
                lower_record.id,
                "reject",
                "The cumulative total decreased; verify the meter reset first.",
            )
            self.assertEqual(rejected.status, "rejected")

            event = create_global_meter_event(
                session,
                admin,
                "replacement",
                0.0,
                "Shared meter replacement confirmed.",
            )
            after_event_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 2.0, 2.0
            )
            after_event = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=after_event_photo.id,
                    odometer_miles=1200,
                ),
            )
            state = get_or_create_global_meter_state(session)
            event_id = event.id
            event_type = event.event_type
            values = (
                state.previous_cumulative_total_litres,
                state.current_cumulative_total_litres,
                state.last_event_id,
                after_event.meter_delta_litres,
                after_event.meter_check_status,
            )

        self.assertEqual(event_type, "replacement")
        self.assertEqual(values, (0.0, 2.0, None, 2.0, "calculated"))
        with Session(self.engine) as session:
            persisted_event = session.get(GlobalMeterEvent, event_id)
        self.assertIsNotNone(persisted_event)

    def test_initial_global_meter_baseline_updates_shared_total(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin = bootstrap_admin(
                session, "admin@example.com", "Admin", "admin-password-123"
            )
            event = create_global_meter_event(
                session,
                admin,
                "baseline",
                Decimal("200.000"),
                "Initial shared meter reading.",
            )
            summary = get_global_meter_summary(session)

            self.assertEqual(event.baseline_total_integer, 200_000)
            self.assertEqual(summary["current_total_integer"], 200_000)
            self.assertEqual(
                summary["current_cumulative_total_litres"], 200.0
            )

    def test_management_dependency_forbids_employees_and_allows_boss(self) -> None:
        employee = Employee(role="employee")
        boss = Employee(role="boss")
        admin = Employee(role="admin")

        with self.assertRaises(HTTPException) as raised:
            require_management(employee)

        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(HTTPException) as raised:
            require_admin(employee)
        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(HTTPException) as raised:
            require_admin(boss)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIs(require_admin(admin), admin)
        self.assertIs(require_management(boss), boss)
        self.assertIs(require_management(admin), admin)

    def test_admin_employee_records_and_summary_support_date_ranges(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)
            emma = session.scalar(
                select(Employee).where(Employee.username == "Tommy1")
            )
            november_start = datetime(2026, 11, 1).date()
            november_end = datetime(2026, 11, 30).date()
            nov_records = list_employee_fuel_records(
                session, emma.id, november_start, november_end
            )
            november = get_admin_fuel_summary(
                session, november_start, november_end
            )
            all_dates = get_admin_fuel_summary(session)
            employee_payload = AdminEmployeeRead.model_validate(
                emma
            ).model_dump(by_alias=True)
            summary_payload = AdminFuelSummaryRead.model_validate(
                november
            ).model_dump(by_alias=True)
            expected_november_cost = sum(
                record.cost
                for record in session.scalars(
                    select(FuelRecord).where(
                        FuelRecord.created_at
                        >= datetime(2026, 11, 1, tzinfo=timezone.utc),
                        FuelRecord.created_at
                        < datetime(2026, 12, 1, tzinfo=timezone.utc),
                    )
                )
            )
            with self.assertRaises(InvalidAdminDateRange):
                get_admin_fuel_summary(
                    session,
                    start_date=november_end,
                    end_date=november_start,
                )
            with self.assertRaises(AdminEmployeeNotFound):
                list_employee_fuel_records(session, 9999)

        self.assertEqual(len(nov_records), 2)
        self.assertEqual(november["fill_count"], 20)
        self.assertAlmostEqual(november["total_fill_litres"], 649.0)
        self.assertEqual(november["total_cost"], expected_november_cost)
        self.assertEqual(november["cost_record_count"], 20)
        self.assertEqual(
            november["top_vehicles"][0]["registration_number"],
            "DD-TOMMY-010",
        )
        self.assertAlmostEqual(
            november["top_vehicles"][0]["total_fill_litres"],
            68.5,
        )
        self.assertEqual(all_dates["fill_count"], 30)
        self.assertAlmostEqual(all_dates["total_fill_litres"], 951.0)
        self.assertEqual(
            all_dates["available_from"],
            datetime(2026, 10, 25).date(),
        )
        self.assertEqual(
            all_dates["available_to"],
            datetime(2026, 11, 13).date(),
        )
        self.assertIn("isActive", employee_payload)
        self.assertIn("totalFillLitres", summary_payload)

    def test_admin_summary_includes_manual_fuel_records(self) -> None:
        recorded_at = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "manual-summary@example.test",
                "Manual Summary Driver",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "MS11 FUL")
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            employee.vehicles.append(vehicle)
            session.flush()
            session.add(
                FuelRecord(
                    reg_number=vehicle.registration_number,
                    fuel_type="Diesel",
                    first_name="Manual",
                    surname="Summary Driver",
                    mileage_miles=4321,
                    capacity=60,
                    litres=12.345,
                    cost=0,
                    employee_id=employee.id,
                    vehicle_id=vehicle.id,
                    current_fill_litres=12.345,
                    cumulative_total_litres=1.234,
                    current_fill_milli_litres=12345,
                    cumulative_total_integer=1234,
                    current_fill_raw_digits="12345",
                    cumulative_total_raw_digits="1234",
                    meter_reading_source="manual",
                    meter_check_status="matched",
                    created_at=recorded_at,
                )
            )
            session.flush()
            summary = get_admin_fuel_summary(
                session,
                start_date=date(2026, 11, 17),
                end_date=date(2026, 11, 17),
            )
            payload = AdminFuelSummaryRead.model_validate(
                summary
            ).model_dump(by_alias=True)

        self.assertEqual(summary["fill_count"], 1)
        self.assertEqual(len(payload["recentRecords"]), 1)
        recent_record = payload["recentRecords"][0]
        self.assertEqual(recent_record["employeeName"], "Manual Summary Driver")
        self.assertEqual(recent_record["regNumber"], "MS11 FUL")
        self.assertEqual(recent_record["meterReadingSource"], "manual")
        self.assertAlmostEqual(recent_record["currentFillLitres"], 12.345)
        self.assertEqual(recent_record["cumulativeTotalInteger"], 1234)

    def test_uncertain_ocr_requires_manual_confirmation_of_total_only(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session, "uncertain@example.test", "Uncertain Worker", "temporary-password"
            )
            vehicle = create_vehicle(session, "un12 cer")
            employee.vehicles.append(vehicle)
            photo = self._create_verified_meter_photo(
                session,
                employee,
                vehicle,
                75,
                107,
                ocr_result=MeterOcrResult(
                    status="uncertain",
                    current_fill_litres=75,
                    cumulative_total_litres=107,
                    current_fill_confidence=30,
                    cumulative_total_confidence=98,
                    message="Current reading is unclear.",
                ),
                verify=False,
            )

            with self.assertRaises(ValueError):
                MeterPhotoVerify.model_validate(
                    {
                        "confirmed": True,
                        "currentFillRawDigits": "75x",
                        "cumulativeTotalRawDigits": "107000",
                    }
                )
            with self.assertRaises(InvalidMeterVerification):
                verify_meter_photo(
                    session,
                    employee,
                    photo.id,
                    Decimal("107.1234"),
                )
            request = MeterPhotoVerify.model_validate(
                {
                    "confirmed": True,
                    "cumulativeTotalRawDigits": "107000",
                }
            )
            verified = verify_meter_photo(
                session,
                employee,
                photo.id,
                request.cumulative_total_litres,
                request.cumulative_total_raw_digits,
            )
            self.assertIsNone(verified.current_fill_litres)
            self.assertEqual(verified.cumulative_total_litres, 107.0)
            self.assertIsNone(verified.top_current_fill_milli_litres)
            self.assertEqual(verified.verification_method, "MANUAL")
            with self.assertRaises(ValueError):
                FuelRecordCreate.model_validate(
                    {
                        "meterPhotoId": photo.id,
                        "odometerMiles": 1000,
                        "employeeId": employee.id,
                        "vehicleId": vehicle.id,
                    }
                )
            with self.assertRaises(ValueError):
                FuelRecordCreate.model_validate(
                    {"meterPhotoId": photo.id, "odometerKm": 1000}
                )

    def test_new_photo_ocr_does_not_store_current_fill_evidence(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "legacy-fill@example.test",
                "Legacy Fill Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "lf12 old")
            employee.vehicles.append(vehicle)
            photo = self._create_verified_meter_photo(
                session,
                employee,
                vehicle,
                22032,
                261.563,
                verify=False,
            )
            verified = verify_meter_photo(session, employee, photo.id)

            self.assertIsNone(verified.current_fill_milli_litres)
            self.assertIsNone(verified.current_fill_litres)
            self.assertIsNone(verified.top_current_fill_milli_litres)
            self.assertIsNone(verified.ocr_current_fill_litres)
            self.assertIsNone(verified.ocr_current_fill_raw_digits)
            self.assertEqual(verified.verification_method, "OPENCV")

    def test_ocr_total_raw_digits_are_stored_as_a_whole_integer(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "legacy-total@example.test",
                "Legacy Total Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "lt12 old")
            employee.vehicles.append(vehicle)
            photo = self._create_verified_meter_photo(
                session,
                employee,
                vehicle,
                75,
                261.563,
                verify=False,
            )
            photo.ocr_cumulative_total_litres = 261.563
            photo.ocr_cumulative_total_raw_digits = "261563"
            verified = verify_meter_photo(session, employee, photo.id)

            self.assertEqual(verified.cumulative_total_integer, 261563)
            self.assertEqual(verified.cumulative_total_litres, 261.563)
            self.assertEqual(verified.cumulative_total_raw_digits, "261563")

    def test_manual_total_warns_for_decrease_without_advancing_total(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "manual-warning@example.test",
                "Manual Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "mw12 arn")
            vehicle.tank_capacity = 50
            employee.vehicles.append(vehicle)
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=100,
                    current_total_integer=100_000,
                    current_total_raw_digits="100000",
                )
            )
            photo = self._create_verified_meter_photo(
                session,
                employee,
                vehicle,
                7.5,
                107.5,
                ocr_result=MeterOcrResult(status="uncertain"),
                verify=False,
            )

            verified = verify_meter_photo(
                session,
                employee,
                photo.id,
                cumulative_total_raw_digits="090000",
            )

            self.assertIsNotNone(verified.verified_at)
            self.assertIsNone(verified.current_fill_litres)
            self.assertEqual(verified.cumulative_total_litres, 90)
            self.assertTrue(
                any(
                    "decreased" in warning
                    for warning in verified.reading_warnings
                )
            )

    def test_long_ocr_message_is_limited_to_database_column_length(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "long-ocr-message@example.test",
                "OCR Message Worker",
                "temporary-password",
            )
            vehicle = create_vehicle(session, "lm12 reg")
            employee.vehicles.append(vehicle)
            photo = self._create_verified_meter_photo(
                session,
                employee,
                vehicle,
                7.5,
                107.5,
                ocr_result=MeterOcrResult(
                    status="uncertain",
                    message="ocr warning; " * 40,
                ),
                verify=False,
            )

            self.assertEqual(len(photo.ocr_message), 255)

    def test_odometer_decrease_requires_single_use_admin_correction(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)
            emma = session.scalar(
                select(Employee).where(Employee.username == "Tommy1")
            )
            admin = bootstrap_admin(
                session,
                "odometer-admin@example.test",
                "Odometer Admin",
                "temporary-admin-password",
            )
            vehicle = session.scalar(
                select(Vehicle).where(
                    Vehicle.registration_number == "DD-TOMMY-001"
                )
            )
            previous_odometer = my_vehicle(session=session, employee=emma)
            self.assertAlmostEqual(
                previous_odometer.last_recorded_odometer_miles, 7944.2
            )
            create_global_meter_event(
                session,
                admin,
                "reset",
                8996.0,
                "Authorized test reset before corrected odometer scenario.",
            )
            photo = self._create_verified_meter_photo(
                session, emma, vehicle, 4.0, 9000.0
            )
            request = FuelRecordCreate(
                meter_photo_id=photo.id, odometer_miles=7456.5
            )

            with self.assertRaisesRegex(FuelSubmissionError, r"\d[\d,]*\.\d mi"):
                save_fuel_record(session, emma, request)

            correction = authorize_odometer_correction(
                session,
                vehicle,
                admin,
                7456.5,
                "Dashboard confirmed the corrected odometer.",
            )
            record = save_fuel_record(session, emma, request)
            correction_values = (
                correction.authorized_odometer_miles,
                correction.previous_odometer_miles,
                correction.used_by_employee_id,
                correction.used_at is not None,
            )
            record_values = (
                record.mileage_miles,
                record.current_odometer_miles,
                record.odometer_correction_id,
            )
            correction_id = correction.id
            emma_id = emma.id

            another_photo = self._create_verified_meter_photo(
                session, emma, vehicle, 3.0, 9003.0
            )
            with self.assertRaisesRegex(FuelSubmissionError, "administrator"):
                save_fuel_record(
                    session,
                    emma,
                    FuelRecordCreate(
                        meter_photo_id=another_photo.id,
                        odometer_miles=7400,
                    ),
                )

        self.assertEqual(correction_values[:2], (7456.5, 7944.2))
        self.assertEqual(correction_values[2], emma_id)
        self.assertTrue(correction_values[3])
        self.assertEqual(record_values, (7456.5, 7456.5, correction_id))

    def test_global_total_updates_across_employees_not_vehicle_records(self) -> None:
        with Session(self.engine) as session, session.begin():
            previous_employee = create_employee(
                session,
                "previous-owner@example.test",
                "Previous Owner",
                "temporary-password",
            )
            current_employee = create_employee(
                session,
                "current-owner@example.test",
                "Current Owner",
                "temporary-password",
            )
            admin = bootstrap_admin(
                session,
                "meter-admin@example.test",
                "Meter Admin",
                "temporary-admin-password",
            )
            boss = create_employee(
                session,
                "meter-boss@example.test",
                "Meter Boss",
                "temporary-password",
                role="boss",
            )
            vehicle = create_vehicle(session, "ab12 cde")
            previous_employee.vehicles.append(vehicle)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60.0
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=90,
                    current_total_integer=90_000,
                    current_total_raw_digits="90000",
                    revision=1,
                )
            )
            photo = self._create_verified_meter_photo(
                session, previous_employee, vehicle, 10.0, 100.0
            )
            save_fuel_record(
                session,
                previous_employee,
                FuelRecordCreate(meter_photo_id=photo.id, odometer_miles=1000),
            )
            current_employee.vehicles.append(vehicle)
            next_photo = self._create_verified_meter_photo(
                session, current_employee, vehicle, 10.0, 110.0
            )
            save_fuel_record(
                session,
                current_employee,
                FuelRecordCreate(meter_photo_id=next_photo.id, odometer_miles=1100),
            )

            employee_vehicle = my_vehicle(
                session=session, employee=current_employee
            )
            admin.vehicles.append(vehicle)
            admin_vehicle = my_vehicle(session=session, employee=admin)
            boss.vehicles.append(vehicle)
            boss_vehicle = my_vehicle(session=session, employee=boss)
            summary = get_global_meter_summary(session)

        self.assertIsNotNone(employee_vehicle)
        self.assertIsNotNone(admin_vehicle)
        self.assertIsNotNone(boss_vehicle)
        self.assertEqual(summary["current_cumulative_total_litres"], 110.0)
        self.assertEqual(summary["previous_cumulative_total_litres"], 100.0)
        self.assertEqual(summary["difference_litres"], 10.0)
        self.assertEqual(summary["last_employee_name"], "Current Owner")
        self.assertEqual(summary["last_vehicle_registration"], "AB12 CDE")
        self.assertNotIn(
            "cumulative_total_litres",
            employee_vehicle.model_dump(),
        )

    def test_total_delta_is_calculated_and_decrease_waits_for_admin_review(
        self,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session, "reset@example.test", "Reset Worker", "temporary-password"
            )
            admin = bootstrap_admin(
                session,
                "meter-admin@example.test",
                "Meter Admin",
                "temporary-admin-password",
            )
            vehicle = create_vehicle(session, "re12 set")
            employee.vehicles.append(vehicle)
            vehicle.fuel_type = "Diesel"
            vehicle.tank_capacity = 60
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=90,
                    current_total_integer=90_000,
                    current_total_raw_digits="90000",
                    revision=1,
                )
            )
            first_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 10.0, 100.0
            )
            first_record = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=first_photo.id,
                    odometer_miles=1000,
                ),
            )

            mismatch_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 3.0, 110.0
            )
            next_record = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=mismatch_photo.id,
                    odometer_miles=1100,
                ),
            )
            self.assertIsInstance(next_record, FuelRecord)
            self.assertEqual(next_record.meter_delta_litres, 10.0)
            summary = get_admin_fuel_summary(session)
            self.assertEqual(
                [item["id"] for item in summary["recent_records"]],
                [next_record.id, first_record.id],
            )
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                110_000,
            )

            reset_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 2.0, 2.0
            )
            request = FuelRecordCreate(
                meter_photo_id=reset_photo.id,
                odometer_miles=1200,
            )
            lower_record = save_fuel_record(session, employee, request)
            self.assertIsInstance(lower_record, MeterReadingReview)
            self.assertTrue(
                any("decreased" in warning for warning in lower_record.warnings)
            )
            self.assertEqual(
                get_or_create_global_meter_state(session).current_total_integer,
                110_000,
            )
            rejected = decide_meter_reading_review(
                session,
                admin,
                lower_record.id,
                "reject",
                "The meter was reset; the photo predates the reset event.",
            )
            self.assertEqual(rejected.status, "rejected")

            event = create_global_meter_event(
                session,
                admin,
                "reset",
                0.0,
                "The shared PIUSI meter was reset for testing.",
            )
            after_reset_photo = self._create_verified_meter_photo(
                session, employee, vehicle, 2.0, 2.0
            )
            after_reset = save_fuel_record(
                session,
                employee,
                FuelRecordCreate(
                    meter_photo_id=after_reset_photo.id,
                    odometer_miles=1300,
                ),
            )
            reset_values = (
                after_reset.meter_epoch,
                after_reset.meter_delta_litres,
                after_reset.meter_check_status,
            )
            event_type = event.event_type

        self.assertEqual(event_type, "reset")
        self.assertEqual(reset_values, (0, 2.0, "calculated"))

    def test_employee_cannot_submit_another_employees_meter_photo(self) -> None:
        with Session(self.engine) as session, session.begin():
            emma = create_employee(
                session, "emma-owner@example.test", "Emma", "temporary-password"
            )
            emma2 = create_employee(
                session, "emma2-owner@example.test", "Emma2", "temporary-password"
            )
            emma_vehicle = create_vehicle(session, "ow12 ner")
            emma.vehicles.append(emma_vehicle)
            emma_vehicle.fuel_type = "Diesel"
            emma_vehicle.tank_capacity = 60
            emma2_vehicle = create_vehicle(session, "ow22 ner")
            emma2.vehicles.append(emma2_vehicle)
            emma2_vehicle.fuel_type = "Diesel"
            emma2_vehicle.tank_capacity = 60
            emma2_photo = self._create_verified_meter_photo(
                session, emma2, emma2_vehicle, 4.0, 14.0
            )

            self.assertIsNone(
                verify_meter_photo(
                    session,
                    emma,
                    emma2_photo.id,
                )
            )
            with self.assertRaises(InvalidMeterVerification):
                verify_meter_photo(
                    session,
                    emma2,
                    emma2_photo.id,
                )
            with self.assertRaises(MeterPhotoNotOwned):
                save_fuel_record(
                    session,
                    emma,
                    FuelRecordCreate(
                        meter_photo_id=emma2_photo.id,
                        odometer_miles=100,
                    ),
                )

    def test_meter_photo_file_is_removed_when_database_transaction_rolls_back(
        self,
    ) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(image_buffer, format="PNG")
        image_data = image_buffer.getvalue()
        with TemporaryDirectory() as upload_directory:
            with patch(
                "backend.app.services.photo_storage.METER_PHOTO_DIRECTORY",
                Path(upload_directory),
            ):
                with Session(self.engine) as session:
                    stored_path = None
                    with self.assertRaises(RuntimeError):
                        with session.begin():
                            employee = create_employee(
                                session,
                                "rollback@example.test",
                                "Rollback Worker",
                                "temporary-password",
                            )
                            vehicle = create_vehicle(session, "cd34 efg")
                            _, qr_payload = issue_vehicle_qr(session, vehicle.id)
                            qr_session = create_qr_session(
                                session, employee, qr_payload
                            )
                            session_token, _, _ = qr_session
                            with patch(
                                "backend.app.services.meter_photos.extract_meter_readings",
                                return_value=MeterOcrResult(
                                    status="unavailable"
                                ),
                            ):
                                stored_photo, _ = store_meter_photo(
                                    session,
                                    employee,
                                    session_token,
                                    image_data,
                                    "image/png",
                                )
                            stored_path = (
                                Path(upload_directory) / stored_photo.storage_key
                            )
                            self.assertTrue(stored_path.is_file())
                            raise RuntimeError("simulate database rollback")

                    self.assertFalse(stored_path.exists())

    def test_private_upload_directory_is_not_mounted_as_static(self) -> None:
        from backend.app.main import app

        route_paths = set(app.openapi()["paths"])
        self.assertIn("/api/meter-photos", route_paths)
        self.assertIn("/api/meter-photos/{meter_photo_id}/verify", route_paths)
        self.assertIn("/api/fuel-records", route_paths)
        self.assertIn("/api/vehicles/me/fuel-records", route_paths)
        self.assertIn(
            "/api/admin/vehicles/{vehicle_id}/odometer-corrections",
            route_paths,
        )
        self.assertIn(
            "/api/admin/vehicles/{vehicle_id}/meter-events", route_paths
        )
        self.assertIn("/api/admin/employees", route_paths)
        self.assertIn(
            "/api/admin/employees/{employee_id}/fuel-records",
            route_paths,
        )
        self.assertIn("/api/admin/fuel-summary", route_paths)
        self.assertIn("/api/management/global-meter", route_paths)
        self.assertIn("/api/management/global-meter/history", route_paths)
        self.assertIn("/api/management/global-meter/events", route_paths)
        self.assertIn(
            "/api/management/global-meter/transactions/{transaction_id}/photo",
            route_paths,
        )
        self.assertFalse(
            any(route_path.startswith("/uploads/") for route_path in route_paths)
        )

    def test_password_hash_and_signed_session(self) -> None:
        password = "temporary-test-password"
        password_hash = hash_password(password)
        self.assertNotEqual(password_hash, password)
        self.assertTrue(verify_password(password, password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

        with patch.dict(os.environ, {"FUEL_AUTH_SECRET": "x" * 40}):
            token = create_access_token(7)
            self.assertEqual(decode_access_token(token), 7)

    def test_demo_seed_is_hashed_repeatable_and_authenticates_all_accounts(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)
            seed_demo_data(session)

        with Session(self.engine) as session:
            employees = list(
                session.scalars(
                    select(Employee)
                    .where(Employee.is_demo.is_(True))
                    .order_by(Employee.username)
                )
            )
            vehicles = list(
                session.scalars(select(Vehicle).where(Vehicle.is_demo.is_(True)))
            )
            records = list(
                session.scalars(
                    select(FuelRecord).where(FuelRecord.is_demo.is_(True))
                )
            )

            self.assertEqual(
                {employee.username for employee in employees},
                set(DEMO_EMPLOYEE_NAMES),
            )
            self.assertEqual(len(vehicles), 10)
            self.assertEqual(len(records), 30)
            self.assertTrue(all(vehicle.employees for vehicle in vehicles))
            self.assertTrue(
                all(
                    record.employee_id is not None and record.vehicle_id is not None
                    for record in records
                )
            )
            for employee in employees:
                assigned_vehicles = [
                    vehicle for vehicle in vehicles if employee in vehicle.employees
                ]
                self.assertEqual(len(assigned_vehicles), 1)
                self.assertNotEqual(employee.password_hash, DEMO_PASSWORD)
                authenticated = authenticate_employee(
                    session,
                    employee.username or "",
                    DEMO_PASSWORD,
                )
                self.assertIsNotNone(authenticated)
                assigned_vehicle = my_vehicle(session=session, employee=authenticated)
                self.assertEqual(
                    assigned_vehicle.id, assigned_vehicles[0].id
                )
                self.assertEqual(
                    assigned_vehicle.registration_number,
                    assigned_vehicles[0].registration_number,
                )
                self.assertIsNotNone(assigned_vehicle.make)
                self.assertIsNotNone(assigned_vehicle.model)
                self.assertIsNotNone(assigned_vehicle.fuel_type)
                self.assertIsNotNone(assigned_vehicle.tank_capacity)
                self.assertIsNotNone(assigned_vehicle.last_recorded_odometer_miles)
                self.assertTrue(assigned_vehicle.is_active)
                self.assertEqual(assigned_vehicle.meter_epoch, 0)

    def test_reset_demo_data_replaces_only_demo_cohort(self) -> None:
        with Session(self.engine) as session, session.begin():
            admin = Employee(
                email="admin@example.test",
                name="Admin",
                password_hash=hash_password("admin-password"),
                role="admin",
                is_active=True,
                is_demo=False,
            )
            boss = Employee(
                email="boss@example.test",
                name="Boss",
                password_hash=hash_password("boss-password"),
                role="boss",
                is_active=True,
                is_demo=False,
            )
            real_employee = Employee(
                email="driver@example.test",
                name="Real Driver",
                password_hash=hash_password("driver-password"),
                role="employee",
                is_active=True,
                is_demo=False,
            )
            real_vehicle = Vehicle(
                registration_number="241-D-100",
                make="Ford",
                model="Transit",
                fuel_type="Diesel",
                tank_capacity=80,
                is_company_vehicle=True,
                is_demo=False,
            )
            session.add_all([admin, boss, real_employee, real_vehicle])
            real_employee.vehicles.append(real_vehicle)

            old_demo_accounts = []
            for index, username in enumerate(LEGACY_DEMO_EMPLOYEE_NAMES, start=1):
                employee = Employee(
                    email=f"{username.lower()}@demo.example.com",
                    username=username,
                    name=username,
                    password_hash=hash_password(DEMO_PASSWORD),
                    role="employee",
                    is_active=True,
                    is_demo=True,
                )
                vehicle = Vehicle(
                    registration_number=f"DD-DEMO-{index:03d}",
                    make="Demo Motors",
                    model=f"Test Van {index:02d}",
                    fuel_type="Diesel",
                    tank_capacity=55 + index,
                    is_company_vehicle=True,
                    is_demo=True,
                )
                employee.vehicles.append(vehicle)
                session.add_all([employee, vehicle])
                old_demo_accounts.append((employee, vehicle))

            session.flush()
            old_employee, old_vehicle = old_demo_accounts[0]
            old_record = FuelRecord(
                reg_number=old_vehicle.registration_number,
                fuel_type="Diesel",
                first_name=old_employee.name,
                surname="Demo",
                mileage_miles=10000,
                capacity=60,
                litres=30,
                cost=51.6,
                employee_id=old_employee.id,
                vehicle_id=old_vehicle.id,
                current_fill_litres=30,
                cumulative_total_litres=5000,
                is_demo=True,
                demo_key="demo:emma:old",
                created_at=datetime(2026, 11, 13, 9, tzinfo=timezone.utc),
            )
            session.add(old_record)
            session.flush()
            old_qr_session = QrSession(
                token_hash="a" * 64,
                employee_id=old_employee.id,
                vehicle_id=old_vehicle.id,
                created_at=old_record.created_at,
                expires_at=old_record.created_at + timedelta(minutes=10),
            )
            session.add(old_qr_session)
            session.flush()
            old_photo = MeterPhoto(
                qr_session_id=old_qr_session.id,
                employee_id=old_employee.id,
                vehicle_id=old_vehicle.id,
                storage_key="old-demo-meter-photo.jpg",
                content_type="image/jpeg",
                size_bytes=128,
                sha256="b" * 64,
                uploaded_at=old_record.created_at,
            )
            session.add(old_photo)
            session.flush()
            old_record.meter_photo_id = old_photo.id
            session.add(
                GlobalMeterState(
                    id=1,
                    current_cumulative_total_litres=5000,
                    last_updated_at=old_record.created_at,
                    last_transaction_id=old_record.id,
                    last_employee_id=old_employee.id,
                    last_vehicle_id=old_vehicle.id,
                    revision=1,
                )
            )
            session.flush()

            admin_id = admin.id
            boss_id = boss.id
            real_employee_id = real_employee.id
            real_vehicle_id = real_vehicle.id
            real_record = FuelRecord(
                reg_number=real_vehicle.registration_number,
                fuel_type="Diesel",
                first_name=real_employee.name,
                surname="Driver",
                mileage_miles=15000,
                capacity=80,
                litres=42,
                cost=72.24,
                employee_id=real_employee.id,
                vehicle_id=real_vehicle.id,
                current_fill_litres=42,
                is_demo=False,
                created_at=datetime(2026, 11, 13, 10, tzinfo=timezone.utc),
            )
            session.add(real_record)
            session.flush()
            real_record_id = real_record.id

            removed_photo_keys = reset_demo_data(session)

            employees = list(session.scalars(select(Employee)))
            demo_employees = [
                employee for employee in employees if employee.is_demo
            ]
            demo_vehicles = list(
                session.scalars(
                    select(Vehicle).where(Vehicle.is_demo.is_(True))
                )
            )
            demo_records = list(
                session.scalars(
                    select(FuelRecord).where(FuelRecord.is_demo.is_(True))
                )
            )
            demo_names = {employee.username for employee in demo_employees}
            demo_registrations = {
                vehicle.registration_number for vehicle in demo_vehicles
                if vehicle.registration_number.startswith("DD-TOMMY-")
            }
            self.assertEqual(removed_photo_keys, ["old-demo-meter-photo.jpg"])
            self.assertEqual(
                session.scalar(select(func.count()).select_from(MeterPhoto)),
                0,
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(QrSession)),
                0,
            )
            self.assertEqual(demo_names, set(DEMO_EMPLOYEE_NAMES))
            self.assertEqual(len(demo_vehicles), 10)
            self.assertEqual(len(demo_registrations), 10)
            self.assertEqual(len(demo_records), 30)
            self.assertIsNotNone(session.get(Employee, admin_id))
            self.assertIsNotNone(session.get(Employee, boss_id))
            self.assertIsNotNone(session.get(Employee, real_employee_id))
            self.assertIsNotNone(session.get(Vehicle, real_vehicle_id))
            self.assertIsNotNone(session.get(FuelRecord, real_record_id))
            self.assertIsNone(
                authenticate_employee(session, "Emma", DEMO_PASSWORD)
            )
            self.assertIsNotNone(
                authenticate_employee(session, "Tommy1", DEMO_PASSWORD)
            )
            state = session.get(GlobalMeterState, 1)
            self.assertEqual(state.current_cumulative_total_litres, 9650)
            self.assertTrue(
                session.get(FuelRecord, state.last_transaction_id).is_demo
            )

    def test_clear_history_preserves_accounts_vehicles_and_assignments(self) -> None:
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            employee = Employee(
                email="history-cleanup@example.test",
                username="cleanup-driver",
                name="Cleanup Driver",
                password_hash=hash_password("temporary-password"),
                role="employee",
                is_active=True,
                is_demo=False,
            )
            vehicle = Vehicle(
                registration_number="CLEAN-001",
                make="Test Motors",
                model="Test Car",
                fuel_type="Diesel",
                tank_capacity=60,
                cumulative_total_litres=1234,
                meter_epoch=2,
            )
            employee.vehicles.append(vehicle)
            session.add_all([employee, vehicle])
            session.flush()

            employee_session = EmployeeSession(
                employee_id=employee.id,
                token_hash="a" * 64,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            qr_session = QrSession(
                token_hash="b" * 64,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                created_at=now,
                expires_at=now + timedelta(minutes=10),
            )
            meter_event = GlobalMeterEvent(
                event_type="reset",
                previous_cumulative_total_litres=1234,
                baseline_cumulative_total_litres=0,
                authorized_by_employee_id=employee.id,
                occurred_at=now,
                notes="Test event for history cleanup.",
            )
            session.add_all([employee_session, qr_session, meter_event])
            session.flush()

            photo = MeterPhoto(
                qr_session_id=qr_session.id,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                storage_key="cleanup-photo.jpg",
                content_type="image/jpeg",
                size_bytes=128,
                sha256="c" * 64,
                uploaded_at=now,
            )
            session.add(photo)
            session.flush()

            record = FuelRecord(
                reg_number=vehicle.registration_number,
                fuel_type="Diesel",
                first_name=employee.name,
                surname="Test",
                mileage_miles=1000,
                capacity=vehicle.tank_capacity,
                litres=10,
                cost=17.2,
                employee_id=employee.id,
                vehicle_id=vehicle.id,
                current_fill_litres=10,
                cumulative_total_litres=1234,
                meter_photo_id=photo.id,
                is_demo=False,
                created_at=now,
            )
            session.add_all(
                [
                    record,
                    VehicleMeterEvent(
                        vehicle_id=vehicle.id,
                        created_by_employee_id=employee.id,
                        meter_epoch=2,
                        event_type="reset",
                        baseline_cumulative_total_litres=0,
                        occurred_at=now,
                        notes="Test vehicle event.",
                    ),
                    VehicleOdometerCorrection(
                        vehicle_id=vehicle.id,
                        authorized_by_employee_id=employee.id,
                        authorized_odometer_miles=900,
                        previous_odometer_miles=1000,
                        notes="Test correction.",
                        created_at=now,
                    ),
                ]
            )
            session.flush()
            state = GlobalMeterState(
                id=1,
                current_cumulative_total_litres=1234,
                last_updated_at=now,
                last_transaction_id=record.id,
                last_employee_id=employee.id,
                last_vehicle_id=vehicle.id,
                last_event_id=meter_event.id,
            )
            session.add(state)
            employee_id = employee.id
            vehicle_id = vehicle.id

            photo_keys = clear_history(session)

            self.assertEqual(photo_keys, ["cleanup-photo.jpg"])
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Employee)),
                1,
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Vehicle)),
                1,
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(FuelRecord)),
                0,
            )
            for history_model in (
                EmployeeSession,
                QrSession,
                MeterPhoto,
                GlobalMeterEvent,
                GlobalMeterState,
                VehicleMeterEvent,
                VehicleOdometerCorrection,
            ):
                self.assertEqual(
                    session.scalar(
                        select(func.count()).select_from(history_model)
                    ),
                    0,
                    history_model.__tablename__,
                )
            kept_employee = session.get(Employee, employee_id)
            kept_vehicle = session.get(Vehicle, vehicle_id)
            self.assertEqual(kept_vehicle.registration_number, "CLEAN-001")
            self.assertEqual(kept_vehicle.cumulative_total_litres, None)
            self.assertEqual(kept_vehicle.meter_epoch, 0)
            self.assertEqual(kept_vehicle.employees, [kept_employee])

    def test_demo_seed_assigns_relative_nct_dates_without_duplicates(self) -> None:
        seed_date = datetime(2026, 11, 15).date()
        with (
            patch(
                "backend.app.services.demo_data.get_irish_today",
                return_value=seed_date,
            ),
            Session(self.engine) as session,
            session.begin(),
        ):
            seed_demo_data(session)
            seed_demo_data(session)

        with Session(self.engine) as session:
            vehicles = list(
                session.scalars(
                    select(Vehicle)
                    .where(Vehicle.is_demo.is_(True))
                    .order_by(Vehicle.registration_number)
                )
            )
            self.assertEqual(len(vehicles), 10)
            self.assertEqual(
                [vehicle.nct_expiry_date for vehicle in vehicles],
                [
                    seed_date + timedelta(days=days)
                    for days in DEMO_NCT_DAYS_REMAINING
                ],
            )
            alert_summary = get_nct_alerts(session, seed_date)
            self.assertEqual(alert_summary["expiring_soon_count"], 3)
            self.assertEqual(alert_summary["expired_count"], 0)
            self.assertEqual(
                [item["registration_number"] for item in alert_summary["alerts"]],
                ["DD-TOMMY-001", "DD-TOMMY-002", "DD-TOMMY-003"],
            )
            self.assertTrue(
                all(item["status"] == "urgent" for item in alert_summary["alerts"])
            )

    def test_nct_alert_boundaries_and_update_recalculate_immediately(self) -> None:
        today = datetime(2026, 11, 15).date()
        with Session(self.engine) as session, session.begin():
            employees = [
                create_employee(
                    session,
                    f"nct-{index}@example.test",
                    f"NCT Driver {index}",
                    "temporary-test-password",
                )
                for index in range(1, 5)
            ]
            vehicles = [
                create_vehicle(session, f"nct{index:02d} test")
                for index in range(1, 5)
            ]
            for vehicle, employee, offset in zip(
                vehicles, employees, (30, 1, 0, -1), strict=True
            ):
                employee.vehicles.append(vehicle)
                vehicle.nct_expiry_date = today + timedelta(days=offset)
            employees[1].vehicles.append(vehicles[0])
            session.flush()

            nct_rows = list_vehicle_nct(session, today)
            shared_vehicle_nct = next(
                item for item in nct_rows if item["vehicle_id"] == vehicles[0].id
            )
            self.assertEqual(
                shared_vehicle_nct["employee_name"],
                "NCT Driver 1, NCT Driver 2",
            )
            alerts = get_nct_alerts(session, today)
            self.assertEqual(
                [item["status"] for item in alerts["alerts"]],
                ["upcoming", "urgent", "expires_today", "expired"],
            )
            self.assertEqual(alerts["expiring_soon_count"], 3)
            self.assertEqual(alerts["expired_count"], 1)

            updated_vehicle = update_vehicle_nct(
                session, vehicles[0].id, today + timedelta(days=60)
            )
            self.assertIsNotNone(updated_vehicle)
            recalculated = list_vehicle_nct(session, today)
            updated = next(
                item for item in recalculated
                if item["vehicle_id"] == vehicles[0].id
            )
            self.assertEqual(updated["status"], "no_alert")
            self.assertEqual(updated["days_remaining"], 60)

    def test_nct_endpoints_allow_management_and_forbid_employee(self) -> None:
        with TemporaryDirectory() as temp_dir:
            api_engine = create_database_engine(
                f"sqlite:///{Path(temp_dir) / 'nct-api.sqlite'}"
            )
            Base.metadata.create_all(api_engine)
            with Session(api_engine) as session, session.begin():
                employee = Employee(
                    email="nct-employee@example.test",
                    name="NCT employee",
                    password_hash="unused",
                    role="employee",
                    is_active=True,
                    is_demo=False,
                )
                session.add(employee)
                session.flush()
                vehicle = create_vehicle(session, "nct01 test")
                employee.vehicles.append(vehicle)
                vehicle.nct_expiry_date = datetime(2026, 11, 22).date()
                vehicle_id = vehicle.id

            employee = Employee(role="employee")
            admin = Employee(role="admin")
            boss = Employee(role="boss")
            original_overrides = app.dependency_overrides.copy()

            async def call_api(
                path: str,
                method: str = "GET",
                payload: dict | None = None,
            ):
                body = (
                    json.dumps(payload).encode("utf-8")
                    if payload is not None
                    else b""
                )
                request_messages = [
                    {"type": "http.request", "body": body, "more_body": False}
                ]
                response_status = None
                response_body = bytearray()

                async def receive():
                    if request_messages:
                        return request_messages.pop(0)
                    return {"type": "http.disconnect"}

                async def send(message):
                    nonlocal response_status
                    if message["type"] == "http.response.start":
                        response_status = message["status"]
                    elif message["type"] == "http.response.body":
                        response_body.extend(message.get("body", b""))

                await app(
                    {
                        "type": "http",
                        "asgi": {"version": "3.0", "spec_version": "2.3"},
                        "http_version": "1.1",
                        "method": method,
                        "scheme": "http",
                        "path": path,
                        "raw_path": path.encode("ascii"),
                        "query_string": b"",
                        "headers": (
                            [(b"content-type", b"application/json")]
                            if payload is not None
                            else []
                        ),
                        "client": ("127.0.0.1", 1234),
                        "server": ("testserver", 8000),
                        "root_path": "",
                    },
                    receive,
                    send,
                )
                result = json.loads(response_body) if response_body else None
                return response_status, result

            try:
                with Session(api_engine) as session, session.begin():
                    app.dependency_overrides[get_db_session] = lambda: session
                    app.dependency_overrides[get_current_employee] = lambda: employee
                    with patch(
                        "backend.app.services.nct.get_irish_today",
                        return_value=datetime(2026, 11, 15).date(),
                    ):
                        denied_status, _ = asyncio.run(
                            call_api("/api/admin/nct-alerts")
                        )
                        self.assertEqual(denied_status, 403)
                        denied_list_status, _ = asyncio.run(
                            call_api("/api/admin/vehicles/nct")
                        )
                        self.assertEqual(denied_list_status, 403)
                        denied_update_status, _ = asyncio.run(
                            call_api(
                                f"/api/admin/vehicles/{vehicle_id}/nct",
                                "PATCH",
                                {"nctExpiryDate": None},
                            )
                        )
                        self.assertEqual(denied_update_status, 403)

                        app.dependency_overrides[get_current_employee] = lambda: admin
                        admin_status, admin_alerts = asyncio.run(
                            call_api("/api/admin/nct-alerts")
                        )
                        self.assertEqual(admin_status, 200)
                        self.assertEqual(
                            admin_alerts["alerts"][0]["status"], "urgent"
                        )
                        vehicles_status, _ = asyncio.run(
                            call_api("/api/admin/vehicles/nct")
                        )
                        self.assertEqual(vehicles_status, 200)

                        app.dependency_overrides[get_current_employee] = lambda: boss
                        boss_status, _ = asyncio.run(
                            call_api("/api/admin/nct-alerts")
                        )
                        self.assertEqual(boss_status, 200)
                        update_status, updated = asyncio.run(
                            call_api(
                                f"/api/admin/vehicles/{vehicle_id}/nct",
                                "PATCH",
                                {"nctExpiryDate": None},
                            )
                        )
                        self.assertEqual(update_status, 200)
                        self.assertEqual(updated["status"], "not_set")
                        missing_vehicle_status, _ = asyncio.run(
                            call_api(
                                "/api/admin/vehicles/9999/nct",
                                "PATCH",
                                {"nctExpiryDate": None},
                            )
                        )
                        self.assertEqual(missing_vehicle_status, 404)
                        invalid_date_status, _ = asyncio.run(
                            call_api(
                                f"/api/admin/vehicles/{vehicle_id}/nct",
                                "PATCH",
                                {"nctExpiryDate": "not-a-date"},
                            )
                        )
                        self.assertEqual(invalid_date_status, 422)

                        app.dependency_overrides[get_current_employee] = lambda: admin
                        invalid_cleanup_status, _ = asyncio.run(
                            call_api(
                                "/api/admin/operational-data/clear",
                                "POST",
                                {"confirmation": "CLEAR DATA"},
                            )
                        )
                        self.assertEqual(invalid_cleanup_status, 422)
                        cleanup_status, cleanup_result = asyncio.run(
                            call_api(
                                "/api/admin/operational-data/clear",
                                "POST",
                                {"confirmation": "CLEAR OPERATIONAL DATA"},
                            )
                        )
                        self.assertEqual(cleanup_status, 200)
                        self.assertEqual(cleanup_result["retainedUsers"], 1)
                        self.assertEqual(cleanup_result["retainedVehicles"], 1)
            finally:
                app.dependency_overrides.clear()
                app.dependency_overrides.update(original_overrides)
                api_engine.dispose()

    def test_fuel_history_is_scoped_to_the_authenticated_employee(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)

        with Session(self.engine) as session:
            emma = session.scalar(
                select(Employee).where(Employee.username == "Tommy1")
            )
            emma2 = session.scalar(
                select(Employee).where(Employee.username == "Tommy2")
            )
            self.assertIsNotNone(emma)
            self.assertIsNotNone(emma2)
            emma_records = read_fuel_records(session=session, employee=emma)
            emma2_records = read_fuel_records(session=session, employee=emma2)
            emma_vehicle_records = my_vehicle_fuel_records(
                session=session, employee=emma
            )
            emma2_vehicle_records = my_vehicle_fuel_records(
                session=session, employee=emma2
            )
            self.assertEqual(len(get_fuel_records(session, emma.id)), 3)

        self.assertEqual(len(emma_records), 3)
        self.assertEqual(len(emma2_records), 3)
        self.assertEqual(
            {record.id for record in emma_vehicle_records},
            {record.id for record in emma_records},
        )
        self.assertEqual(
            {record.id for record in emma2_vehicle_records},
            {record.id for record in emma2_records},
        )
        self.assertTrue(all(record.employee_id == emma.id for record in emma_records))
        self.assertTrue(all(record.employee_id == emma2.id for record in emma2_records))
        self.assertTrue(
            {record.vehicle_id for record in emma_records}.isdisjoint(
                {record.vehicle_id for record in emma2_records}
            )
        )

    def test_boss_vehicle_registration_suggestions_filter_active_vehicles(self) -> None:
        with Session(self.engine) as session, session.begin():
            boss = create_employee(
                session,
                "vehicle-suggest-boss@example.test",
                "Vehicle Suggest Boss",
                "temporary-password",
                role="boss",
            )
            employee = create_employee(
                session,
                "vehicle-suggest-employee@example.test",
                "Vehicle Suggest Employee",
                "temporary-password",
            )
            vehicles = [
                create_vehicle(session, registration)
                for registration in (
                    "AB12 CDE",
                    "XY12 ZZZ",
                    "ZX99 ABC",
                )
            ]
            vehicles[2].is_active = False

            self.assertEqual(
                vehicle_registration_suggestions(
                    session=session, employee=boss, search=None
                ),
                ["AB12 CDE", "XY12 ZZZ"],
            )
            self.assertEqual(
                vehicle_registration_suggestions(
                    session=session, employee=boss, search="12"
                ),
                ["AB12 CDE", "XY12 ZZZ"],
            )
            self.assertEqual(
                vehicle_registration_suggestions(
                    session=session, employee=boss, search="ab%"
                ),
                [],
            )
            with self.assertRaises(HTTPException) as forbidden:
                vehicle_registration_suggestions(
                    session=session, employee=employee, search=None
                )
            self.assertEqual(forbidden.exception.status_code, 403)

    def test_boss_vehicle_suggestions_prioritize_registration_prefixes(self) -> None:
        with Session(self.engine) as session, session.begin():
            boss = create_employee(
                session,
                "vehicle-prefix-boss@example.test",
                "Vehicle Prefix Boss",
                "temporary-password",
                role="boss",
            )
            for index in range(12):
                create_vehicle(session, f"A18MATCH{index:02d}")
            create_vehicle(session, "182SO547")

            suggestions = vehicle_registration_suggestions(
                session=session, employee=boss, search="18"
            )

        self.assertEqual(suggestions[0], "182SO547")
        self.assertIn("182SO547", suggestions)

    def test_assigned_vehicle_lookup_hides_other_employees_vehicle(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)

        with Session(self.engine) as session:
            emma = session.scalar(
                select(Employee).where(Employee.username == "Tommy1")
            )
            emma2_vehicle = session.scalar(
                select(Vehicle).where(
                    Vehicle.registration_number == "DD-TOMMY-002"
                )
            )
            with self.assertRaises(HTTPException) as raised:
                lookup_vehicle(
                    emma2_vehicle.registration_number,
                    session=session,
                    employee=emma,
                )

        self.assertEqual(raised.exception.status_code, 404)

    def test_demo_seed_refuses_real_employee_email_collision(self) -> None:
        with Session(self.engine) as session, session.begin():
            employee = create_employee(
                session,
                "tommy1@demo.example.com",
                "Real Employee",
                "temporary-test-password",
            )
            original_hash = employee.password_hash

        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError, "non-demo employee"):
                with session.begin():
                    seed_demo_data(session)

        with Session(self.engine) as session:
            employee = session.scalar(
                select(Employee).where(Employee.email == "tommy1@demo.example.com")
            )
            self.assertEqual(employee.name, "Real Employee")
            self.assertEqual(employee.password_hash, original_hash)
            self.assertFalse(employee.is_demo)

    def test_employee_session_logout_and_expiry(self) -> None:
        with Session(self.engine) as session, session.begin():
            seed_demo_data(session)
            login_rate_limiter.reset("127.0.0.1")
            request = Request(
                {
                    "type": "http",
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/auth/login",
                    "raw_path": b"/api/auth/login",
                    "query_string": b"",
                    "headers": [],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 8000),
                }
            )
            response = Response()
            employee = login_endpoint(
                LoginRequest(username="Tommy1", password=DEMO_PASSWORD),
                response,
                request,
                session,
            )
            self.assertEqual(employee.username, "Tommy1")
            cookie = SimpleCookie(response.headers["set-cookie"])
            token = cookie[SESSION_COOKIE_NAME].value
            self.assertEqual(get_employee_for_session(session, token).id, employee.id)

            logout_response = Response()
            logout_endpoint(logout_response, session, token)
            self.assertEqual(logout_response.status_code, 204)
            self.assertIsNone(get_employee_for_session(session, token))

            new_token = create_employee_session(session, employee)
            token_hash = sha256(new_token.encode("utf-8")).hexdigest()
            employee_session = session.scalar(
                select(EmployeeSession).where(
                    EmployeeSession.token_hash == token_hash
                )
            )
            employee_session.expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
            session.flush()
            self.assertIsNone(get_employee_for_session(session, new_token))

    def test_login_rate_limit_allows_five_attempts_then_blocks(self) -> None:
        limiter = LoginRateLimiter(limit=5, window_seconds=60)
        for _ in range(5):
            self.assertEqual(limiter.consume("127.0.0.1"), 0)
        self.assertGreater(limiter.consume("127.0.0.1"), 0)
        limiter.reset("127.0.0.1")
        self.assertEqual(limiter.consume("127.0.0.1"), 0)


if __name__ == "__main__":
    unittest.main()
