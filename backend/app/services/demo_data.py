from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import hash_password
from backend.app.models import (
    Employee,
    EmployeeSession,
    FuelRecord,
    GlobalMeterState,
    MeterPhoto,
    QrSession,
    Vehicle,
    VehicleMeterEvent,
    VehicleOdometerCorrection,
)
from backend.app.repositories.vehicles import is_employee_assigned_to_vehicle
from backend.app.services.nct import get_irish_today


DEMO_EMPLOYEE_NAMES = (
    "Tommy1",
    "Tommy2",
    "Tommy3",
    "Tommy4",
    "Tommy5",
    "Tommy6",
    "Tommy7",
    "Tommy8",
    "Tommy9",
    "Tommy10",
)
LEGACY_DEMO_EMPLOYEE_NAMES = (
    "Emma",
    "Emma2",
    "Emma3",
    "Emma4",
    "Emma5",
    "Emma6",
    "Emma7",
    "Emma8",
    "Emma9",
    "Emma10",
)
DEMO_PASSWORD = "123456"
DEMO_FUEL_DATES = (
    datetime(2026, 10, 25, 9, tzinfo=timezone.utc),
    datetime(2026, 11, 4, 9, tzinfo=timezone.utc),
    datetime(2026, 11, 13, 9, tzinfo=timezone.utc),
)
DEMO_NCT_DAYS_REMAINING = (7, 15, 28, 60, 75, 90, 120, 150, 180, 200)


def _find_demo_employee(session: Session, username: str) -> Employee | None:
    employee = session.scalar(
        select(Employee).where(Employee.username.ilike(username))
    )
    if employee is not None and not employee.is_demo:
        raise ValueError(
            f"Refusing to overwrite non-demo employee with username {username!r}."
        )
    return employee


def _get_or_create_employee(session: Session, username: str) -> Employee:
    email = f"{username.lower()}@demo.example.com"
    employee = _find_demo_employee(session, username)
    if employee is None:
        email_owner = session.scalar(
            select(Employee).where(Employee.email.ilike(email))
        )
        if email_owner is not None:
            raise ValueError(
                f"Refusing to overwrite non-demo employee with email {email!r}."
            )
        employee = Employee(
            email=email,
            username=username,
            name=username,
            password_hash=hash_password(DEMO_PASSWORD),
            role="employee",
            is_active=True,
            is_demo=True,
        )
        session.add(employee)
    else:
        employee.email = email
        employee.name = username
        employee.password_hash = hash_password(DEMO_PASSWORD)
        employee.role = "employee"
        employee.is_active = True
        employee.is_demo = True
    session.flush()
    return employee


def _get_or_create_vehicle(
    session: Session,
    employee: Employee,
    index: int,
) -> Vehicle:
    registration_number = f"DD-TOMMY-{index:03d}"
    vehicle = session.scalar(
        select(Vehicle).where(
            Vehicle.registration_number == registration_number
        )
    )
    if vehicle is not None and not vehicle.is_demo:
        raise ValueError(
            "Refusing to overwrite non-demo vehicle "
            f"{registration_number!r}."
        )
    if vehicle is None:
        conflicting_assignment = session.scalar(
            select(Vehicle).where(
                Vehicle.employees.any(Employee.id == employee.id),
                Vehicle.is_demo.is_(True),
            )
        )
        if conflicting_assignment is not None:
            raise ValueError(
                f"Demo employee {employee.username!r} already has another "
                "demo vehicle assigned."
            )
        vehicle = Vehicle(
            registration_number=registration_number,
            make="Demo Motors",
            model=f"Test Van {index:02d}",
            fuel_type="Diesel",
            tank_capacity=55.0 + index,
            is_active=True,
            is_demo=True,
        )
        session.add(vehicle)
        session.flush()
        employee.vehicles.append(vehicle)
    else:
        if not is_employee_assigned_to_vehicle(vehicle, employee.id):
            employee.vehicles.append(vehicle)
        vehicle.make = "Demo Motors"
        vehicle.model = f"Test Van {index:02d}"
        vehicle.fuel_type = "Diesel"
        vehicle.tank_capacity = 55.0 + index
        vehicle.is_active = True
        vehicle.is_demo = True
    session.flush()
    return vehicle


def _upsert_fuel_record(
    session: Session,
    employee: Employee,
    vehicle: Vehicle,
    employee_index: int,
    log_index: int,
) -> None:
    demo_key = f"demo:{employee.username.lower()}:{log_index + 1}"
    record = session.scalar(
        select(FuelRecord).where(FuelRecord.demo_key == demo_key)
    )
    if record is not None and not record.is_demo:
        raise ValueError(f"Refusing to overwrite non-demo fuel record {demo_key!r}.")
    if record is None:
        record = FuelRecord(demo_key=demo_key, is_demo=True)
        session.add(record)

    record.employee_id = employee.id
    record.vehicle_id = vehicle.id
    record.reg_number = vehicle.registration_number
    record.fuel_type = vehicle.fuel_type or "Diesel"
    record.first_name = employee.name
    record.surname = "Demo"
    record.mileage_miles = round(
        (12000 + employee_index * 425 + log_index * 180) / 1.609344, 1
    )
    record.capacity = vehicle.tank_capacity or 60.0
    record.litres = 28.0 + employee_index * 0.4 + log_index * 1.5
    record.cost = round(record.litres * 1.72, 2)
    record.current_fuel_reading = 14.0 + employee_index + log_index * 4.0
    record.cumulative_meter_reading = (
        5000 + employee_index * 275 + log_index * 950
    )
    record.current_fill_litres = record.litres
    record.cumulative_total_litres = record.cumulative_meter_reading
    record.meter_delta_litres = None
    record.meter_check_status = "legacy"
    record.meter_epoch = 0
    record.meter_photo_id = None
    record.is_demo = True
    record.created_at = DEMO_FUEL_DATES[log_index]


def seed_demo_data(session: Session) -> None:
    nct_base_date = get_irish_today()
    for employee_index, username in enumerate(DEMO_EMPLOYEE_NAMES, start=1):
        employee = _get_or_create_employee(session, username)
        vehicle = _get_or_create_vehicle(session, employee, employee_index)
        vehicle.nct_expiry_date = nct_base_date + timedelta(
            days=DEMO_NCT_DAYS_REMAINING[employee_index - 1]
        )
        for log_index in range(len(DEMO_FUEL_DATES)):
            _upsert_fuel_record(
                session,
                employee,
                vehicle,
                employee_index,
                log_index,
            )
    session.flush()


def reset_demo_data(session: Session) -> list[str]:
    employees = list(
        session.scalars(
            select(Employee)
            .where(Employee.is_demo.is_(True), Employee.role == "employee")
            .order_by(Employee.id)
        )
    )
    names = {employee.username for employee in employees}
    if employees and names not in (
        frozenset(LEGACY_DEMO_EMPLOYEE_NAMES),
        frozenset(DEMO_EMPLOYEE_NAMES),
    ):
        raise ValueError(
            "Refusing to reset demo data: expected exactly the existing Emma "
            "or Tommy demo employee cohort."
        )
    if employees and len(employees) != len(DEMO_EMPLOYEE_NAMES):
        raise ValueError(
            "Refusing to reset demo data: the demo employee cohort is incomplete."
        )

    employees_by_name = {employee.username: employee for employee in employees}
    employee_ids = {employee.id for employee in employees}
    target_employees: list[Employee] = []
    target_vehicles: list[Vehicle] = []
    for index, target_name in enumerate(DEMO_EMPLOYEE_NAMES, start=1):
        employee = employees_by_name.get(target_name) or employees_by_name.get(
            LEGACY_DEMO_EMPLOYEE_NAMES[index - 1]
        )
        if employee is None:
            continue
        email = f"{target_name.lower()}@demo.example.com"
        username_owner = session.scalar(
            select(Employee).where(
                Employee.username.ilike(target_name),
                Employee.id != employee.id,
            )
        )
        email_owner = session.scalar(
            select(Employee).where(
                Employee.email.ilike(email),
                Employee.id != employee.id,
            )
        )
        if username_owner is not None or email_owner is not None:
            raise ValueError(
                f"Refusing to replace demo employee: {target_name!r} is already "
                "in use by another account."
            )

        assigned_vehicles = [
            vehicle for vehicle in employee.vehicles if vehicle.is_demo
        ]
        if len(assigned_vehicles) != 1 or any(
            assigned_employee.id not in employee_ids
            for assigned_employee in assigned_vehicles[0].employees
        ):
            raise ValueError(
                f"Refusing to reset {employee.username!r}: expected one dedicated "
                "demo vehicle."
            )
        vehicle = assigned_vehicles[0]
        registration_number = f"DD-TOMMY-{index:03d}"
        registration_owner = session.scalar(
            select(Vehicle).where(
                Vehicle.registration_number == registration_number,
                Vehicle.id != vehicle.id,
            )
        )
        if registration_owner is not None:
            raise ValueError(
                f"Refusing to replace demo vehicle: {registration_number!r} "
                "is already in use."
            )
        target_employees.append(employee)
        target_vehicles.append(vehicle)

    vehicle_ids = {vehicle.id for vehicle in target_vehicles}
    if not employee_ids:
        seed_demo_data(session)
        return []

    photos = list(
        session.scalars(
            select(MeterPhoto).where(
                (MeterPhoto.employee_id.in_(employee_ids))
                | (MeterPhoto.vehicle_id.in_(vehicle_ids))
                | (MeterPhoto.verified_by_employee_id.in_(employee_ids))
            )
        )
    )
    photo_ids = {photo.id for photo in photos}
    if photo_ids:
        unrelated_record = session.scalar(
            select(FuelRecord.id).where(
                FuelRecord.meter_photo_id.in_(photo_ids),
                FuelRecord.is_demo.is_(False),
            )
        )
        if unrelated_record is not None:
            raise ValueError(
                "Refusing to remove a demo meter photo linked to a non-demo "
                "fuel record."
            )

    demo_records = list(
        session.scalars(
            select(FuelRecord).where(
                FuelRecord.is_demo.is_(True),
                (FuelRecord.employee_id.in_(employee_ids))
                | (FuelRecord.vehicle_id.in_(vehicle_ids)),
            )
        )
    )
    demo_record_ids = {record.id for record in demo_records}
    meter_state = session.get(GlobalMeterState, 1)
    reset_global_meter = bool(
        meter_state is not None
        and meter_state.last_transaction_id in demo_record_ids
        and meter_state.last_event_id is None
    )
    if reset_global_meter:
        meter_state.last_transaction_id = None
        meter_state.last_employee_id = None
        meter_state.last_vehicle_id = None
        meter_state.current_cumulative_total_litres = None
        meter_state.previous_cumulative_total_litres = None
        meter_state.last_updated_at = None

    for record in demo_records:
        session.delete(record)
    for photo in photos:
        session.delete(photo)
    session.flush()

    qr_sessions = list(
        session.scalars(
            select(QrSession).where(
                (QrSession.employee_id.in_(employee_ids))
                | (QrSession.vehicle_id.in_(vehicle_ids))
            )
        )
    )
    for qr_session in qr_sessions:
        session.delete(qr_session)

    session.flush()
    photo_storage_keys = [photo.storage_key for photo in photos]

    correction_records = list(
        session.scalars(
            select(VehicleOdometerCorrection).where(
                (VehicleOdometerCorrection.vehicle_id.in_(vehicle_ids))
                | (VehicleOdometerCorrection.authorized_by_employee_id.in_(employee_ids))
                | (VehicleOdometerCorrection.used_by_employee_id.in_(employee_ids))
            )
        )
    )
    for correction in correction_records:
        session.delete(correction)
    meter_events = list(
        session.scalars(
            select(VehicleMeterEvent).where(
                (VehicleMeterEvent.vehicle_id.in_(vehicle_ids))
                | (VehicleMeterEvent.created_by_employee_id.in_(employee_ids))
            )
        )
    )
    for meter_event in meter_events:
        session.delete(meter_event)

    revoked_at = datetime.now(timezone.utc)
    active_sessions = session.scalars(
        select(EmployeeSession).where(
            EmployeeSession.employee_id.in_(employee_ids),
            EmployeeSession.revoked_at.is_(None),
        )
    )
    for employee_session in active_sessions:
        employee_session.revoked_at = revoked_at

    for index, (employee, vehicle) in enumerate(
        zip(target_employees, target_vehicles), start=1
    ):
        employee.username = DEMO_EMPLOYEE_NAMES[index - 1]
        employee.email = (
            f"{DEMO_EMPLOYEE_NAMES[index - 1].lower()}@demo.example.com"
        )
        employee.name = DEMO_EMPLOYEE_NAMES[index - 1]
        employee.password_hash = hash_password(DEMO_PASSWORD)
        employee.is_active = True
        vehicle.registration_number = f"DD-TOMMY-{index:03d}"
        vehicle.qr_token_hash = None
        vehicle.cumulative_total_litres = None
        vehicle.meter_epoch = 0

    session.flush()
    seed_demo_data(session)

    if reset_global_meter and meter_state is not None:
        seeded_records = list(
            session.scalars(
                select(FuelRecord)
                .where(
                    FuelRecord.is_demo.is_(True),
                    FuelRecord.employee_id.in_(employee_ids),
                )
                .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
                .limit(2)
            )
        )
        latest = seeded_records[0]
        previous = seeded_records[1] if len(seeded_records) > 1 else None
        meter_state.current_cumulative_total_litres = (
            latest.cumulative_total_litres
        )
        meter_state.previous_cumulative_total_litres = (
            previous.cumulative_total_litres if previous is not None else None
        )
        meter_state.last_updated_at = latest.created_at
        meter_state.last_transaction_id = latest.id
        meter_state.last_employee_id = latest.employee_id
        meter_state.last_vehicle_id = latest.vehicle_id
        meter_state.revision += 1

    session.flush()
    return photo_storage_keys
