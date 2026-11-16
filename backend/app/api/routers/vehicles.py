from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas.vehicle import VehicleRead
from backend.app.schemas import FuelRecordRead
from backend.app.repositories.fuel_records import (
    get_latest_vehicle_odometer,
)
from backend.app.services.fuel_records import get_assigned_vehicle_fuel_records
from backend.app.repositories.vehicles import is_vehicle_available_to_employee
from backend.app.services.vehicles import get_assigned_vehicle, identify_vehicle


router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


@router.get("/me", response_model=VehicleRead | None)
def my_vehicle(
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> VehicleRead | None:
    vehicle = get_assigned_vehicle(session, employee.id)
    if vehicle is None:
        return None
    vehicle_read = VehicleRead.model_validate(vehicle)
    return vehicle_read.model_copy(
        update={
            "last_recorded_odometer_miles": get_latest_vehicle_odometer(
                session, vehicle.id
            ),
        }
    )


@router.get("/me/fuel-records", response_model=list[FuelRecordRead])
def my_vehicle_fuel_records(
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> list[FuelRecordRead]:
    vehicle, records = get_assigned_vehicle_fuel_records(session, employee.id)
    if vehicle is None:
        return []
    return records


@router.get("/lookup/{registration_number}", response_model=VehicleRead)
def lookup_vehicle(
    registration_number: str,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> VehicleRead:
    vehicle = identify_vehicle(session, registration_number)
    if vehicle is None or not is_vehicle_available_to_employee(
        vehicle, employee.id
    ):
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return VehicleRead.model_validate(vehicle)
