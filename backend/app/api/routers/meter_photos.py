from typing import Annotated
import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from typing import Literal
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.core.config import is_manual_meter_entry_enabled
from backend.app.db.session import get_db_session
from backend.app.models import Employee, MeterPhoto
from backend.app.repositories.vehicles import get_vehicle_by_id
from backend.app.repositories.meter_photos import get_meter_photo_by_id
from backend.app.schemas.meter_photo import (
    MeterPhotoRead,
    MeterPhotoSessionCreate,
    MeterPhotoSessionRead,
    MeterPhotoVerify,
    QrSessionCreate,
)
from backend.app.services.meter_photos import (
    InvalidMeterVerification,
    MAX_METER_PHOTO_BYTES,
    InvalidMeterPhoto,
    InvalidQrSession,
    UnsupportedMeterPhotoType,
    create_vehicle_photo_session,
    create_qr_session,
    store_meter_photo,
    verify_meter_photo,
)
from backend.app.services.photo_storage import PhotoStorageError, read_photo


logger = logging.getLogger(__name__)
router = APIRouter(tags=["meter photos"])


@router.post(
    "/api/meter-photos/sessions",
    response_model=MeterPhotoSessionRead,
    status_code=201,
)
def start_vehicle_photo_session(
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
    request: MeterPhotoSessionCreate | None = None,
) -> MeterPhotoSessionRead:
    created = create_vehicle_photo_session(
        session,
        employee,
        request.vehicle_id if request is not None else None,
    )
    if created is None:
        raise HTTPException(
            status_code=404,
            detail="Vehicle not found or unavailable for meter photo capture.",
        )
    session_token, registration_number, expires_at = created
    response.headers["Cache-Control"] = "no-store"
    return MeterPhotoSessionRead(
        session_token=session_token,
        registration_number=registration_number,
        expires_at=expires_at,
    )


@router.get("/api/meter-photos/policy")
def meter_photo_policy(
    _: Annotated[Employee, Depends(get_current_employee)],
) -> dict[str, bool]:
    return {"manual_entry_enabled": is_manual_meter_entry_enabled()}


@router.post(
    "/api/qr/sessions",
    response_model=MeterPhotoSessionRead,
    status_code=201,
)
def start_qr_session(
    request: QrSessionCreate,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> MeterPhotoSessionRead:
    created = create_qr_session(session, employee, request.qr_payload)
    if created is None:
        raise HTTPException(status_code=404, detail="Vehicle QR code is not valid.")
    session_token, registration_number, expires_at = created
    response.headers["Cache-Control"] = "no-store"
    return MeterPhotoSessionRead(
        session_token=session_token,
        registration_number=registration_number,
        expires_at=expires_at,
    )


@router.post("/api/meter-photos", response_model=MeterPhotoRead, status_code=201)
def upload_meter_photo(
    session_token: Annotated[str, Form(min_length=1, max_length=128)],
    photo: Annotated[UploadFile, File()],
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
    reading_mode: Annotated[Literal["ocr", "manual"], Form()] = "ocr",
) -> MeterPhotoRead:
    content = photo.file.read(MAX_METER_PHOTO_BYTES + 1)
    if len(content) > MAX_METER_PHOTO_BYTES:
        raise HTTPException(
            status_code=413, detail="Meter photos must be 10 MB or smaller."
        )

    try:
        stored_photo, registration_number = store_meter_photo(
            session,
            employee,
            session_token,
            content,
            photo.content_type,
            reading_mode=reading_mode,
        )
    except UnsupportedMeterPhotoType as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except InvalidMeterPhoto as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except InvalidQrSession as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PhotoStorageError as error:
        logger.exception("Could not store an uploaded meter photo.")
        raise HTTPException(
            status_code=503, detail="Photo storage is temporarily unavailable."
        ) from error
    except IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="This QR session has already been used.",
        ) from error

    response.headers["Cache-Control"] = "no-store"
    return _meter_photo_read(
        stored_photo,
        registration_number,
    )


@router.get("/api/meter-photos/{meter_photo_id}/content")
def read_meter_photo_content(
    meter_photo_id: int,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> Response:
    meter_photo = get_meter_photo_by_id(session, meter_photo_id)
    if meter_photo is None or (
        employee.role not in {"admin", "boss"}
        and meter_photo.employee_id != employee.id
    ):
        raise HTTPException(status_code=404, detail="Meter photo not found.")
    try:
        content = read_photo(meter_photo.storage_key)
    except PhotoStorageError as error:
        logger.exception("Could not retrieve a meter photo.")
        raise HTTPException(
            status_code=503, detail="Photo storage is temporarily unavailable."
        ) from error
    if content is None:
        raise HTTPException(status_code=404, detail="Meter photo not found.")
    return Response(
        content=content,
        media_type=meter_photo.content_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.patch(
    "/api/meter-photos/{meter_photo_id}/verify",
    response_model=MeterPhotoRead,
)
def confirm_meter_readings(
    meter_photo_id: int,
    request: MeterPhotoVerify,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> MeterPhotoRead:
    try:
        meter_photo = verify_meter_photo(
            session,
            employee,
            meter_photo_id,
            request.cumulative_total_litres,
            request.cumulative_total_raw_digits,
        )
    except InvalidMeterVerification as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if meter_photo is None:
        raise HTTPException(status_code=404, detail="Meter photo not found.")
    vehicle = get_vehicle_by_id(session, meter_photo.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Meter photo vehicle not found.")
    response.headers["Cache-Control"] = "no-store"
    return _meter_photo_read(meter_photo, vehicle.registration_number)


def _meter_photo_read(
    meter_photo: MeterPhoto, registration_number: str
) -> MeterPhotoRead:
    return MeterPhotoRead(
        id=meter_photo.id,
        content_type=meter_photo.content_type,
        size_bytes=meter_photo.size_bytes,
        uploaded_at=meter_photo.uploaded_at,
        registration_number=registration_number,
        ocr_status=meter_photo.ocr_status,
        ocr_cumulative_total_litres=meter_photo.ocr_cumulative_total_litres,
        ocr_cumulative_total_confidence=meter_photo.ocr_cumulative_total_confidence,
        ocr_provider=meter_photo.ocr_provider,
        ocr_cumulative_total_raw_digits=(
            meter_photo.ocr_cumulative_total_raw_digits
        ),
        ocr_cumulative_total_segment_raw_digits=(
            meter_photo.ocr_cumulative_total_segment_raw_digits
        ),
        suggested_cumulative_total_raw_digits=(
            meter_photo.suggested_cumulative_total_raw_digits
        ),
        ocr_cumulative_total_decimal_position=(
            meter_photo.ocr_cumulative_total_decimal_position
        ),
        ocr_cumulative_total_segment_confidence=(
            meter_photo.ocr_cumulative_total_segment_confidence
        ),
        ocr_warnings=meter_photo.ocr_warnings,
        reading_warnings=meter_photo.reading_warnings,
        cumulative_total_manually_corrected=(
            meter_photo.cumulative_total_manually_corrected
        ),
        current_fill_litres=meter_photo.current_fill_litres,
        cumulative_total_litres=meter_photo.cumulative_total_litres,
        current_fill_milli_litres=meter_photo.current_fill_milli_litres,
        cumulative_total_integer=meter_photo.cumulative_total_integer,
        previous_global_total_integer=meter_photo.previous_global_total_integer,
        cumulative_total_raw_digits=meter_photo.cumulative_total_raw_digits,
        reading_source=meter_photo.reading_source,
        fill_calculation=meter_photo.fill_calculation,
        reconciliation_status=meter_photo.reconciliation_status,
        verified_at=meter_photo.verified_at,
        verification_method=meter_photo.verification_method,
        ocr_message=meter_photo.ocr_message,
    )
