import hashlib
import secrets
from datetime import date

from sqlalchemy.orm import Session

from backend.app.models import Vehicle
from backend.app.repositories.vehicles import (
    add_vehicle,
    get_employee_vehicle,
    get_vehicle_by_registration,
    get_vehicle_by_id,
    get_vehicle_by_qr_hash,
    list_active_vehicles,
)

QR_PAYLOAD_PREFIX = "DIESEL-DESK:"


def identify_vehicle(session: Session, registration_number: str) -> Vehicle | None:
    return get_vehicle_by_registration(session, registration_number.upper())


def create_vehicle(
    session: Session,
    registration_number: str,
    *,
    make: str | None = None,
    model: str | None = None,
    fuel_type: str | None = None,
    tank_capacity: float | None = None,
    nct_expiry_date: date | None = None,
    is_company_vehicle: bool = True,
) -> Vehicle:
    vehicle = Vehicle(
        registration_number=registration_number.strip().upper(),
        make=make,
        model=model,
        fuel_type=fuel_type,
        tank_capacity=tank_capacity,
        nct_expiry_date=nct_expiry_date,
        is_company_vehicle=is_company_vehicle,
        is_active=True,
    )
    return add_vehicle(session, vehicle)


def get_registered_vehicles(session: Session) -> list[Vehicle]:
    return list_active_vehicles(session)


def get_assigned_vehicle(session: Session, employee_id: int) -> Vehicle | None:
    return get_employee_vehicle(session, employee_id)


def issue_vehicle_qr(session: Session, vehicle_id: int) -> tuple[Vehicle, str] | None:
    vehicle = get_vehicle_by_id(session, vehicle_id)
    if vehicle is None:
        return None

    token = secrets.token_urlsafe(32)
    vehicle.qr_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session.flush()
    return vehicle, f"{QR_PAYLOAD_PREFIX}{token}"
