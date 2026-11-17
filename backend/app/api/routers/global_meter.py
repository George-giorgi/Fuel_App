from typing import Annotated
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_management
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas.global_meter import (
    GlobalMeterEventCreate,
    GlobalMeterEventRead,
    GlobalMeterHistoryRead,
    GlobalMeterSummaryRead,
)
from backend.app.services.global_meter import (
    GlobalMeterConcurrentUpdate,
    create_global_meter_event,
    get_global_meter_photo,
    get_global_meter_summary,
    list_global_meter_history,
)
from backend.app.services.photo_storage import PhotoStorageError


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/management/global-meter",
    tags=["global meter"],
)


@router.get("", response_model=GlobalMeterSummaryRead)
def read_global_meter(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> GlobalMeterSummaryRead:
    return GlobalMeterSummaryRead.model_validate(get_global_meter_summary(session))


@router.get("/history", response_model=list[GlobalMeterHistoryRead])
def read_global_meter_history(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GlobalMeterHistoryRead]:
    return [
        GlobalMeterHistoryRead.model_validate(entry)
        for entry in list_global_meter_history(session, limit)
    ]


@router.post("/events", response_model=GlobalMeterEventRead, status_code=201)
def record_global_meter_event(
    request: GlobalMeterEventCreate,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(require_management)],
) -> GlobalMeterEventRead:
    try:
        event = create_global_meter_event(
            session,
            employee,
            request.event_type,
            request.baseline_cumulative_total_litres,
            request.notes,
        )
    except GlobalMeterConcurrentUpdate as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return GlobalMeterEventRead.model_validate(event)


@router.get("/transactions/{transaction_id}/photo")
def read_global_meter_transaction_photo(
    transaction_id: int,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> Response:
    try:
        stored_photo = get_global_meter_photo(session, transaction_id)
    except PhotoStorageError as error:
        logger.exception("Could not retrieve a global meter photo.")
        raise HTTPException(
            status_code=503, detail="Photo storage is temporarily unavailable."
        ) from error
    if stored_photo is None:
        raise HTTPException(status_code=404, detail="Meter photo not found.")
    content, content_type = stored_photo
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store"},
    )
