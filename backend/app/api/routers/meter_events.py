from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_admin
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.repositories.vehicles import get_vehicle_by_id
from backend.app.schemas.meter_event import MeterEventCreate, MeterEventRead
from backend.app.services.vehicle_meter_events import create_vehicle_meter_event


router = APIRouter(
    prefix="/api/admin/vehicles",
    tags=["vehicle meter events"],
)


@router.post("/{vehicle_id}/meter-events", response_model=MeterEventRead, status_code=201)
def record_vehicle_meter_event(
    vehicle_id: int,
    request: MeterEventCreate,
    session: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Employee, Depends(require_admin)],
) -> MeterEventRead:
    vehicle = get_vehicle_by_id(session, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    event = create_vehicle_meter_event(
        session,
        vehicle,
        admin,
        request.event_type,
        request.baseline_cumulative_total_litres,
        request.notes,
        request.occurred_at,
    )
    return MeterEventRead.model_validate(event)
