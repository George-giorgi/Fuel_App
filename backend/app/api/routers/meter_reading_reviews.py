from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_admin
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas.fuel_record import (
    MeterReadingReviewDecision,
    MeterReadingReviewRead,
)
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    decide_meter_reading_review,
    list_meter_reading_reviews,
)
from backend.app.services.global_meter import GlobalMeterConcurrentUpdate


router = APIRouter(
    prefix="/api/admin/meter-reading-reviews",
    tags=["meter reading reviews"],
)


@router.get("", response_model=list[MeterReadingReviewRead])
def read_meter_reading_reviews(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> list[MeterReadingReviewRead]:
    return [
        MeterReadingReviewRead.model_validate(review)
        for review in list_meter_reading_reviews(session)
    ]


@router.post("/{review_id}/decision", response_model=MeterReadingReviewRead)
def decide_review(
    review_id: int,
    request: MeterReadingReviewDecision,
    session: Annotated[Session, Depends(get_db_session)],
    reviewer: Annotated[Employee, Depends(require_admin)],
) -> MeterReadingReviewRead:
    try:
        review = decide_meter_reading_review(
            session,
            reviewer,
            review_id,
            request.decision,
            request.note,
        )
    except GlobalMeterConcurrentUpdate as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FuelSubmissionError as error:
        status_code = 404 if str(error) == "Meter reading review not found." else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return MeterReadingReviewRead.model_validate(review)
