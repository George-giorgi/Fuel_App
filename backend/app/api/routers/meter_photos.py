from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.db.session import get_db_session
from backend.app.models import Employee, MeterPhoto
from backend.app.repositories.vehicles import get_vehicle_by_id
from backend.app.schemas.meter_photo import (
    MeterPhotoRead,
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
    create_assigned_vehicle_photo_session,
    create_qr_session,
    store_meter_photo,
    verify_meter_photo,
)
router = APIRouter(tags=["meter photos"])


@router.post(
    "/api/meter-photos/sessions",
    response_model=MeterPhotoSessionRead,
    status_code=201,
)
def start_assigned_vehicle_photo_session(
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> MeterPhotoSessionRead:
    created = create_assigned_vehicle_photo_session(session, employee)
    if created is None:
        raise HTTPException(
            status_code=404,
            detail="No assigned vehicle is available for meter photo capture.",
        )
    session_token, registration_number, expires_at = created
    response.headers["Cache-Control"] = "no-store"
    return MeterPhotoSessionRead(
        session_token=session_token,
        registration_number=registration_number,
        expires_at=expires_at,
    )


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
async def upload_meter_photo(
    session_token: Annotated[str, Form(min_length=1, max_length=128)],
    photo: Annotated[UploadFile, File()],
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> MeterPhotoRead:
    content = await photo.read(MAX_METER_PHOTO_BYTES + 1)
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
        )
    except UnsupportedMeterPhotoType as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except InvalidMeterPhoto as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except InvalidQrSession as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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
        ocr_current_fill_litres=meter_photo.ocr_current_fill_litres,
        ocr_cumulative_total_litres=meter_photo.ocr_cumulative_total_litres,
        ocr_current_fill_confidence=meter_photo.ocr_current_fill_confidence,
        ocr_cumulative_total_confidence=meter_photo.ocr_cumulative_total_confidence,
        current_fill_litres=meter_photo.current_fill_litres,
        cumulative_total_litres=meter_photo.cumulative_total_litres,
        verified_at=meter_photo.verified_at,
        verification_method=meter_photo.verification_method,
        ocr_message=meter_photo.ocr_message,
    )
