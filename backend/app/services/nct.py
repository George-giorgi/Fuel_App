from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Vehicle


IRELAND_TIME_ZONE = ZoneInfo("Europe/Dublin")


def get_irish_today() -> date:
    return datetime.now(IRELAND_TIME_ZONE).date()


def _nct_status(expiry_date: date | None, today: date) -> tuple[str, int | None]:
    if expiry_date is None:
        return "not_set", None

    days_remaining = (expiry_date - today).days
    if days_remaining < 0:
        return "expired", days_remaining
    if days_remaining == 0:
        return "expires_today", 0
    if days_remaining <= 29:
        return "urgent", days_remaining
    if days_remaining <= 30:
        return "upcoming", days_remaining
    return "no_alert", days_remaining


def list_vehicle_nct(
    session: Session,
    today: date | None = None,
) -> list[dict[str, object]]:
    current_date = today or get_irish_today()
    rows = session.scalars(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .order_by(Vehicle.registration_number, Vehicle.id)
    ).all()
    vehicles = []
    for vehicle in rows:
        employee_names = ", ".join(
            sorted(employee.name for employee in vehicle.employees)
        ) or None
        status, days_remaining = _nct_status(vehicle.nct_expiry_date, current_date)
        vehicles.append(
            {
                "vehicle_id": vehicle.id,
                "registration_number": vehicle.registration_number,
                "make": vehicle.make,
                "model": vehicle.model,
                "employee_name": employee_names,
                "nct_expiry_date": vehicle.nct_expiry_date,
                "days_remaining": days_remaining,
                "status": status,
            }
        )
    return vehicles


def get_vehicle_nct(
    session: Session,
    vehicle_id: int,
    today: date | None = None,
) -> dict[str, object] | None:
    current_date = today or get_irish_today()
    vehicle = session.scalar(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .where(Vehicle.id == vehicle_id)
    )
    if vehicle is None:
        return None

    employee_name = ", ".join(
        sorted(employee.name for employee in vehicle.employees)
    ) or None
    status, days_remaining = _nct_status(vehicle.nct_expiry_date, current_date)
    return {
        "vehicle_id": vehicle.id,
        "registration_number": vehicle.registration_number,
        "make": vehicle.make,
        "model": vehicle.model,
        "employee_name": employee_name,
        "nct_expiry_date": vehicle.nct_expiry_date,
        "days_remaining": days_remaining,
        "status": status,
    }


def get_nct_alerts(
    session: Session,
    today: date | None = None,
) -> dict[str, object]:
    current_date = today or get_irish_today()
    vehicles = list_vehicle_nct(session, current_date)
    alerts = [
        vehicle
        for vehicle in vehicles
        if vehicle["status"] in {"upcoming", "urgent", "expires_today", "expired"}
    ]
    return {
        "today": current_date,
        "expiring_soon_count": sum(
            1
            for vehicle in alerts
            if vehicle["days_remaining"] is not None
            and 0 <= vehicle["days_remaining"] <= 30
        ),
        "expired_count": sum(1 for vehicle in alerts if vehicle["status"] == "expired"),
        "alerts": alerts,
    }


def update_vehicle_nct(
    session: Session,
    vehicle_id: int,
    expiry_date: date | None,
) -> Vehicle | None:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        return None
    vehicle.nct_expiry_date = expiry_date
    session.flush()
    return vehicle
