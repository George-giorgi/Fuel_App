import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas import FuelRecordRead
from backend.app.schemas.fuel_record import FuelRecordCreate
from backend.app.services import get_fuel_records
from backend.app.services.fuel_records import (
    FuelSubmissionError,
    MeterPhotoNotOwned,
    MeterPhotoNotVerified,
    create_fuel_record as save_fuel_record,
)
from backend.app.services.global_meter import GlobalMeterConcurrentUpdate


router = APIRouter(prefix="/api/fuel-records", tags=["fuel records"])


@router.get("", response_model=list[FuelRecordRead])
def read_fuel_records(
    session: Session = Depends(get_db_session),
    employee: Employee = Depends(get_current_employee),
) -> list[FuelRecordRead]:
    return get_fuel_records(session, employee.id)


@router.post("", response_model=FuelRecordRead, status_code=201)
def create_fuel_record(
    request: FuelRecordCreate,
    session: Session = Depends(get_db_session),
    employee: Employee = Depends(get_current_employee),
) -> FuelRecordRead:
    try:
        return save_fuel_record(session, employee, request)
    except MeterPhotoNotOwned as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MeterPhotoNotVerified as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except GlobalMeterConcurrentUpdate as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FuelSubmissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="This meter photo is already linked to a fuel record.",
        ) from error
    except OperationalError as error:
        error_code = getattr(error.orig, "sqlite_errorcode", None)
        if error_code not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            raise
        raise HTTPException(
            status_code=409,
            detail=(
                "Another fuel submission is being saved. Wait briefly, refresh, "
                "and review the latest meter reading before retrying."
            ),
        ) from error
