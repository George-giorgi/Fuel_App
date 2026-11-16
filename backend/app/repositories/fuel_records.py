from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import FuelRecord


def list_fuel_records(session: Session, employee_id: int) -> list[FuelRecord]:
    statement = (
        select(FuelRecord)
        .where(FuelRecord.employee_id == employee_id)
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
    )
    return list(session.scalars(statement).all())


def list_vehicle_fuel_records(
    session: Session, vehicle_id: int, employee_id: int
) -> list[FuelRecord]:
    statement = (
        select(FuelRecord)
        .where(
            FuelRecord.vehicle_id == vehicle_id,
            FuelRecord.employee_id == employee_id,
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
    )
    return list(session.scalars(statement).all())


def get_latest_meter_record(
    session: Session, vehicle_id: int, meter_epoch: int
) -> FuelRecord | None:
    statement = (
        select(FuelRecord)
        .where(
            FuelRecord.vehicle_id == vehicle_id,
            FuelRecord.meter_epoch == meter_epoch,
            FuelRecord.cumulative_total_litres.is_not(None),
            FuelRecord.is_demo.is_(False),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
    )
    return session.scalar(statement)


def get_latest_vehicle_record(
    session: Session, vehicle_id: int
) -> FuelRecord | None:
    statement = (
        select(FuelRecord)
        .where(FuelRecord.vehicle_id == vehicle_id)
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
    )
    return session.scalar(statement)


def get_latest_vehicle_odometer(session: Session, vehicle_id: int) -> float | None:
    record = get_latest_vehicle_record(session, vehicle_id)
    return record.mileage_miles if record is not None else None
