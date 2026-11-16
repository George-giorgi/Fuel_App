from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import (
    Employee,
    Vehicle,
    VehicleMeterEvent,
    VehicleOdometerCorrection,
)


def get_vehicle_by_registration(
    session: Session, registration_number: str
) -> Vehicle | None:
    return session.scalar(
        select(Vehicle).where(
            Vehicle.registration_number == registration_number,
            Vehicle.is_active.is_(True),
        )
    )


def is_employee_assigned_to_vehicle(vehicle: Vehicle, employee_id: int) -> bool:
    return any(employee.id == employee_id for employee in vehicle.employees)


def is_vehicle_available_to_employee(vehicle: Vehicle, employee_id: int) -> bool:
    return not vehicle.employees or is_employee_assigned_to_vehicle(
        vehicle, employee_id
    )


def get_vehicle_by_id(session: Session, vehicle_id: int) -> Vehicle | None:
    return session.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.is_active.is_(True),
        )
    )


def get_employee_vehicle(session: Session, employee_id: int) -> Vehicle | None:
    return session.scalar(
        select(Vehicle)
        .join(Vehicle.employees)
        .where(
            Employee.id == employee_id,
            Vehicle.is_active.is_(True),
        )
        .order_by(Vehicle.id)
        .limit(1)
    )


def get_vehicle_by_qr_hash(session: Session, token_hash: str) -> Vehicle | None:
    return session.scalar(
        select(Vehicle).where(
            Vehicle.qr_token_hash == token_hash,
            Vehicle.is_active.is_(True),
        )
    )


def list_active_vehicles(session: Session) -> list[Vehicle]:
    return list(
        session.scalars(
            select(Vehicle)
            .options(selectinload(Vehicle.employees))
            .where(Vehicle.is_active.is_(True))
            .order_by(Vehicle.registration_number)
        )
    )


def get_vehicle_meter_event(
    session: Session, vehicle_id: int, meter_epoch: int
) -> VehicleMeterEvent | None:
    return session.scalar(
        select(VehicleMeterEvent).where(
            VehicleMeterEvent.vehicle_id == vehicle_id,
            VehicleMeterEvent.meter_epoch == meter_epoch,
        )
    )


def get_odometer_correction(
    session: Session, vehicle_id: int, odometer_miles: float
) -> VehicleOdometerCorrection | None:
    return session.scalar(
        select(VehicleOdometerCorrection)
        .where(
            VehicleOdometerCorrection.vehicle_id == vehicle_id,
            VehicleOdometerCorrection.authorized_odometer_miles
            == odometer_miles,
            VehicleOdometerCorrection.used_at.is_(None),
        )
        .order_by(VehicleOdometerCorrection.id.desc())
        .limit(1)
    )


def add_vehicle(session: Session, vehicle: Vehicle) -> Vehicle:
    session.add(vehicle)
    session.flush()
    return vehicle
