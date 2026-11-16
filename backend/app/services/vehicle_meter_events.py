from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models import (
    Employee,
    Vehicle,
    VehicleMeterEvent,
    VehicleOdometerCorrection,
)
from backend.app.repositories.fuel_records import get_latest_vehicle_odometer


def create_vehicle_meter_event(
    session: Session,
    vehicle: Vehicle,
    admin: Employee,
    event_type: str,
    baseline_cumulative_total_litres: float,
    notes: str,
    occurred_at: datetime | None = None,
) -> VehicleMeterEvent:
    happened_at = occurred_at or datetime.now(timezone.utc)
    if happened_at.tzinfo is None:
        happened_at = happened_at.replace(tzinfo=timezone.utc)
    else:
        happened_at = happened_at.astimezone(timezone.utc)

    vehicle.meter_epoch += 1
    vehicle.cumulative_total_litres = baseline_cumulative_total_litres
    event = VehicleMeterEvent(
        vehicle_id=vehicle.id,
        created_by_employee_id=admin.id,
        meter_epoch=vehicle.meter_epoch,
        event_type=event_type,
        baseline_cumulative_total_litres=baseline_cumulative_total_litres,
        occurred_at=happened_at,
        notes=notes.strip(),
    )
    session.add(event)
    session.flush()
    return event


def authorize_odometer_correction(
    session: Session,
    vehicle: Vehicle,
    admin: Employee,
    authorized_odometer_miles: float,
    notes: str,
) -> VehicleOdometerCorrection:
    previous_odometer_miles = get_latest_vehicle_odometer(session, vehicle.id)
    if previous_odometer_miles is None:
        raise ValueError(
            "An odometer correction requires an existing recorded vehicle reading."
        )
    if authorized_odometer_miles >= previous_odometer_miles:
        raise ValueError(
            "A correction must be lower than the vehicle's latest recorded odometer."
        )

    correction = VehicleOdometerCorrection(
        vehicle_id=vehicle.id,
        authorized_by_employee_id=admin.id,
        authorized_odometer_miles=authorized_odometer_miles,
        previous_odometer_miles=previous_odometer_miles,
        notes=notes.strip(),
        created_at=datetime.now(timezone.utc),
    )
    session.add(correction)
    session.flush()
    return correction
