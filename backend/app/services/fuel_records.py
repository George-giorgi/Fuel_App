from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_meter_tolerance_litres
from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterState,
    Vehicle,
    VehicleOdometerCorrection,
)
from backend.app.repositories.fuel_records import (
    get_latest_vehicle_record,
    list_fuel_records,
    list_vehicle_fuel_records,
)
from backend.app.repositories.meter_photos import get_meter_photo_by_id
from backend.app.repositories.vehicles import (
    get_employee_vehicle,
    get_odometer_correction,
    get_vehicle_by_id,
    is_employee_assigned_to_vehicle,
)
from backend.app.schemas.fuel_record import FuelRecordCreate
from backend.app.services.global_meter import (
    get_or_create_global_meter_state,
    update_global_meter_after_fill,
)


class FuelSubmissionError(ValueError):
    pass


class MeterPhotoNotOwned(FuelSubmissionError):
    pass


class MeterPhotoNotVerified(FuelSubmissionError):
    pass


class MeterResetRequired(FuelSubmissionError):
    pass


def get_fuel_records(session: Session, employee_id: int) -> list[FuelRecord]:
    return list_fuel_records(session, employee_id)


def get_assigned_vehicle_fuel_records(
    session: Session, employee_id: int
) -> tuple[Vehicle | None, list[FuelRecord]]:
    vehicle = get_employee_vehicle(session, employee_id)
    if vehicle is None:
        return None, []
    return vehicle, list_vehicle_fuel_records(session, vehicle.id, employee_id)


def create_fuel_record(
    session: Session,
    employee: Employee,
    request: FuelRecordCreate,
) -> FuelRecord:
    if request.vehicle_id is not None and employee.role != "boss":
        raise FuelSubmissionError("Only boss accounts can select another vehicle.")

    vehicle = (
        get_vehicle_by_id(session, request.vehicle_id)
        if request.vehicle_id is not None
        else get_employee_vehicle(session, employee.id)
    )
    if vehicle is None or (
        request.vehicle_id is None
        and not is_employee_assigned_to_vehicle(vehicle, employee.id)
    ):
        raise FuelSubmissionError("No vehicle is assigned to this employee.")

    meter_photo = get_meter_photo_by_id(session, request.meter_photo_id)
    if (
        meter_photo is None
        or meter_photo.employee_id != employee.id
        or meter_photo.vehicle_id != vehicle.id
    ):
        raise MeterPhotoNotOwned("Meter photo not found for the assigned vehicle.")
    if meter_photo.verified_at is None:
        raise MeterPhotoNotVerified(
            "Verify both meter readings against the photo before submitting."
        )
    if meter_photo.current_fill_litres is None:
        raise MeterPhotoNotVerified("The verified current-fill reading is missing.")
    if meter_photo.cumulative_total_litres is None:
        raise MeterPhotoNotVerified("The verified cumulative reading is missing.")
    if vehicle.fuel_type is None or vehicle.tank_capacity is None:
        raise FuelSubmissionError(
            "The assigned vehicle's fuel type and tank capacity must be configured "
            "by an administrator before submission."
        )
    if session.scalar(
        select(FuelRecord.id).where(FuelRecord.meter_photo_id == meter_photo.id)
    ):
        raise FuelSubmissionError("This meter photo is already linked to a fuel record.")

    if (
        vehicle.fuel_type not in {"Diesel", "AdBlue", "Petrol"}
        or vehicle.tank_capacity <= 0
    ):
        raise FuelSubmissionError("The assigned vehicle details are invalid.")

    latest_vehicle_record = get_latest_vehicle_record(session, vehicle.id)
    odometer_correction: VehicleOdometerCorrection | None = None
    if (
        latest_vehicle_record is not None
        and request.odometer_miles < latest_vehicle_record.mileage_miles
    ):
        odometer_correction = get_odometer_correction(
            session, vehicle.id, request.odometer_miles
        )
        if (
            odometer_correction is None
            or odometer_correction.previous_odometer_miles
            != latest_vehicle_record.mileage_miles
        ):
            raise FuelSubmissionError(
                "The odometer is below the vehicle's previous recorded reading "
                f"({latest_vehicle_record.mileage_miles:,.1f} mi). "
                "An administrator must authorize this exact corrected reading "
                "before it can be submitted."
            )

    global_meter_state: GlobalMeterState = get_or_create_global_meter_state(session)
    previous_total = global_meter_state.current_cumulative_total_litres
    cumulative_total = meter_photo.cumulative_total_litres
    meter_delta = (
        cumulative_total - previous_total if previous_total is not None else None
    )
    if meter_delta is not None and meter_delta < 0:
        raise MeterResetRequired(
            "The cumulative total decreased. An administrator must record a "
            "meter reset or replacement before this fill can be submitted."
        )

    if meter_delta is None:
        meter_check_status = "baseline"
    elif abs(meter_delta - meter_photo.current_fill_litres) <= (
        get_meter_tolerance_litres()
    ):
        meter_check_status = "matched"
    else:
        meter_check_status = "discrepancy"

    first_name, _, surname = employee.name.partition(" ")
    now = datetime.now(timezone.utc)
    if odometer_correction is not None:
        odometer_correction.used_by_employee_id = employee.id
        odometer_correction.used_at = now
    record = FuelRecord(
        reg_number=vehicle.registration_number,
        fuel_type=vehicle.fuel_type,
        first_name=first_name,
        surname=surname,
        mileage_miles=request.odometer_miles,
        capacity=vehicle.tank_capacity,
        litres=meter_photo.current_fill_litres,
        cost=0,
        employee_id=employee.id,
        vehicle_id=vehicle.id,
        current_fuel_reading=None,
        cumulative_meter_reading=cumulative_total,
        current_fill_litres=meter_photo.current_fill_litres,
        cumulative_total_litres=cumulative_total,
        meter_delta_litres=meter_delta,
        meter_check_status=meter_check_status,
        meter_epoch=vehicle.meter_epoch,
        meter_photo_id=meter_photo.id,
        odometer_correction_id=(
            odometer_correction.id if odometer_correction is not None else None
        ),
        is_demo=employee.is_demo,
        demo_key=(
            f"global-meter-test:{employee.username or employee.id}:"
            f"{meter_photo.id}"
            if employee.is_demo
            else None
        ),
        created_at=now,
    )
    session.add(record)
    session.flush()
    update_global_meter_after_fill(
        session,
        global_meter_state,
        record,
        employee,
        vehicle,
        now,
    )
    return record
