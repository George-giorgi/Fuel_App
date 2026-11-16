from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import math
import secrets
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from backend.app.core.config import get_meter_tolerance_litres
from backend.app.models import (
    Employee,
    GlobalMeterState,
    MeterPhoto,
    QrSession,
    Vehicle,
)
from backend.app.repositories.meter_photos import (
    add_meter_photo,
    add_qr_session,
    get_meter_photo_by_id,
    get_qr_session_by_hash,
)
from backend.app.repositories.vehicles import (
    get_employee_vehicle,
    get_vehicle_by_id,
    get_vehicle_by_qr_hash,
    is_vehicle_available_to_employee,
)
from backend.app.services.vehicles import QR_PAYLOAD_PREFIX
from backend.app.services.meter_ocr import extract_meter_readings
from backend.app.services.photo_storage import store_photo


QR_SESSION_MINUTES = 10
MAX_METER_PHOTO_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_METER_OCR_MESSAGE_LENGTH = 255
PHOTO_TYPES = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png": ("PNG", ".png"),
}


class UnsupportedMeterPhotoType(ValueError):
    pass


class InvalidMeterPhoto(ValueError):
    pass


class InvalidQrSession(ValueError):
    pass


class InvalidMeterVerification(ValueError):
    pass


def _meter_reading_warnings(
    session: Session,
    vehicle: Vehicle,
    current_fill_litres: float | Decimal | None,
    cumulative_total_litres: float | Decimal | None,
) -> list[str]:
    warnings_found = []
    if (
        vehicle.tank_capacity is not None
        and current_fill_litres is not None
        and Decimal(str(current_fill_litres))
        > Decimal(str(vehicle.tank_capacity))
    ):
        warnings_found.append(
            "Current fill exceeds the configured vehicle tank capacity."
        )

    global_meter = session.get(GlobalMeterState, 1)
    previous_total = (
        global_meter.current_cumulative_total_litres
        if global_meter is not None
        else None
    )
    if previous_total is not None and cumulative_total_litres is not None:
        delta = Decimal(str(cumulative_total_litres)) - Decimal(str(previous_total))
        if delta < 0:
            warnings_found.append(
                "Cumulative total is below the previous accepted reading; confirm a meter reset or replacement."
            )
        elif current_fill_litres is not None and abs(
            delta - Decimal(str(current_fill_litres))
        ) > Decimal(str(get_meter_tolerance_litres())):
            warnings_found.append(
                "Cumulative increase does not match the current fill; review the readings."
            )
    return warnings_found


def create_qr_session(
    session: Session, employee: Employee, qr_payload: str
) -> tuple[str, str, datetime] | None:
    payload = qr_payload.strip()
    if not payload.startswith(QR_PAYLOAD_PREFIX):
        return None

    qr_token = payload.removeprefix(QR_PAYLOAD_PREFIX)
    if not qr_token:
        return None

    token_hash = sha256(qr_token.encode("utf-8")).hexdigest()
    vehicle = get_vehicle_by_qr_hash(session, token_hash)
    if vehicle is None or not is_vehicle_available_to_employee(
        vehicle, employee.id
    ):
        return None

    return _create_photo_session(session, employee, vehicle)


def create_assigned_vehicle_photo_session(
    session: Session, employee: Employee
) -> tuple[str, str, datetime] | None:
    vehicle = get_employee_vehicle(session, employee.id)
    if vehicle is None:
        return None

    return _create_photo_session(session, employee, vehicle)


def create_vehicle_photo_session(
    session: Session, employee: Employee, vehicle_id: int | None = None
) -> tuple[str, str, datetime] | None:
    if vehicle_id is None:
        return create_assigned_vehicle_photo_session(session, employee)
    if employee.role != "boss":
        return None
    vehicle = get_vehicle_by_id(session, vehicle_id)
    if vehicle is None:
        return None
    return _create_photo_session(session, employee, vehicle)


def _create_photo_session(
    session: Session, employee: Employee, vehicle: Vehicle
) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=QR_SESSION_MINUTES)
    session_token = secrets.token_urlsafe(32)
    add_qr_session(
        session,
        QrSession(
            token_hash=sha256(session_token.encode("utf-8")).hexdigest(),
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            created_at=now,
            expires_at=expires_at,
        ),
    )
    return session_token, vehicle.registration_number, expires_at


def validate_meter_photo(content: bytes, content_type: str | None) -> str:
    photo_type = PHOTO_TYPES.get(content_type or "")
    if photo_type is None:
        raise UnsupportedMeterPhotoType("Only JPEG and PNG meter photos are accepted.")

    expected_format, _ = photo_type
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format:
                    raise InvalidMeterPhoto(
                        "The photo content does not match its declared image type."
                    )
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidMeterPhoto("The image dimensions are too large.")
                image.verify()
    except InvalidMeterPhoto:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as error:
        raise InvalidMeterPhoto("The uploaded file is not a valid image.") from error
    return photo_type[1]


def store_meter_photo(
    session: Session,
    employee: Employee,
    session_token: str,
    content: bytes,
    content_type: str | None,
) -> tuple[MeterPhoto, str]:
    token_hash = sha256(session_token.encode("utf-8")).hexdigest()
    qr_session = get_qr_session_by_hash(session, token_hash)
    if qr_session is None or qr_session.employee_id != employee.id:
        raise InvalidQrSession("The QR session is invalid, expired, or already used.")

    now = datetime.now(timezone.utc)
    expires_at = qr_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)
    if (
        qr_session.consumed_at is not None
        or expires_at <= now
    ):
        raise InvalidQrSession("The QR session is invalid, expired, or already used.")

    vehicle = get_vehicle_by_id(session, qr_session.vehicle_id)
    if vehicle is None:
        raise InvalidQrSession("The QR session vehicle is no longer active.")

    extension = validate_meter_photo(content, content_type)
    storage_key, stored_path = store_photo(
        content,
        extension,
        content_type or "",
    )
    if stored_path is not None:
        session.info.setdefault("rollback_upload_paths", []).append(stored_path)

    meter_photo = MeterPhoto(
        qr_session_id=qr_session.id,
        employee_id=employee.id,
        vehicle_id=qr_session.vehicle_id,
        storage_key=storage_key,
        content_type=content_type or "",
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        uploaded_at=now,
    )
    ocr_result = extract_meter_readings(content)
    meter_photo.ocr_status = ocr_result.status
    meter_photo.ocr_current_fill_litres = ocr_result.current_fill_litres
    meter_photo.ocr_cumulative_total_litres = ocr_result.cumulative_total_litres
    meter_photo.ocr_current_fill_confidence = (
        ocr_result.current_fill_confidence
    )
    meter_photo.ocr_cumulative_total_confidence = (
        ocr_result.cumulative_total_confidence
    )
    meter_photo.ocr_message = (
        ocr_result.message[:MAX_METER_OCR_MESSAGE_LENGTH]
        if ocr_result.message is not None
        else None
    )
    meter_photo.ocr_provider = ocr_result.provider
    meter_photo.ocr_current_fill_raw_digits = (
        ocr_result.current_fill_raw_digits
    )
    meter_photo.ocr_current_fill_decimal_position = (
        ocr_result.current_fill_decimal_position
    )
    meter_photo.ocr_cumulative_total_raw_digits = (
        ocr_result.cumulative_total_raw_digits
    )
    meter_photo.ocr_cumulative_total_decimal_position = (
        ocr_result.cumulative_total_decimal_position
    )
    meter_photo.ocr_current_fill_segment_confidence = (
        ocr_result.current_fill_segment_confidence
    )
    meter_photo.ocr_cumulative_total_segment_confidence = (
        ocr_result.cumulative_total_segment_confidence
    )
    warnings_found = list(ocr_result.warnings)
    warnings_found.extend(
        _meter_reading_warnings(
            session,
            vehicle,
            ocr_result.current_fill_litres,
            ocr_result.cumulative_total_litres,
        )
    )
    meter_photo.ocr_warnings = list(dict.fromkeys(warnings_found))
    qr_session.consumed_at = now
    add_meter_photo(session, meter_photo)

    return meter_photo, vehicle.registration_number


def verify_meter_photo(
    session: Session,
    employee: Employee,
    meter_photo_id: int,
    current_fill_litres: Decimal | None = None,
    cumulative_total_litres: Decimal | None = None,
) -> MeterPhoto | None:
    meter_photo = get_meter_photo_by_id(session, meter_photo_id)
    if meter_photo is None or meter_photo.employee_id != employee.id:
        return None
    if meter_photo.verified_at is not None:
        raise InvalidMeterVerification("This meter photo has already been verified.")
    vehicle = get_vehicle_by_id(session, meter_photo.vehicle_id)
    if vehicle is None:
        return None
    if employee.role != "boss":
        assigned_vehicle = get_employee_vehicle(session, employee.id)
        if assigned_vehicle is None or assigned_vehicle.id != vehicle.id:
            return None
    if (current_fill_litres is None) != (cumulative_total_litres is None):
        raise InvalidMeterVerification(
            "Enter both meter readings or neither."
        )
    if (
        cumulative_total_litres is not None
        and cumulative_total_litres.as_tuple().exponent < 0
    ):
        raise InvalidMeterVerification(
            "Cumulative Total must be entered as whole litres."
        )
    if current_fill_litres is not None and cumulative_total_litres is not None:
        if (
            not current_fill_litres.is_finite()
            or not cumulative_total_litres.is_finite()
            or current_fill_litres <= 0
            or cumulative_total_litres < 0
        ):
            raise InvalidMeterVerification("Enter valid non-negative meter readings.")
        final_current_fill = float(current_fill_litres)
        final_cumulative_total = float(cumulative_total_litres)
        manual_correction = (
            meter_photo.ocr_status != "ready"
            or meter_photo.ocr_current_fill_litres is None
            or meter_photo.ocr_cumulative_total_litres is None
            or Decimal(str(meter_photo.ocr_current_fill_litres))
            != current_fill_litres
            or Decimal(str(meter_photo.ocr_cumulative_total_litres))
            != cumulative_total_litres
        )
    else:
        if (
            meter_photo.ocr_status != "ready"
            or meter_photo.ocr_current_fill_litres is None
            or meter_photo.ocr_cumulative_total_litres is None
            or meter_photo.ocr_current_fill_confidence is None
            or meter_photo.ocr_cumulative_total_confidence is None
            or meter_photo.ocr_current_fill_confidence < 60
            or meter_photo.ocr_cumulative_total_confidence < 60
            or meter_photo.ocr_current_fill_litres <= 0
            or meter_photo.ocr_cumulative_total_litres < 0
            or not math.isfinite(meter_photo.ocr_current_fill_litres)
            or not math.isfinite(meter_photo.ocr_cumulative_total_litres)
            or not float(meter_photo.ocr_cumulative_total_litres).is_integer()
        ):
            raise InvalidMeterVerification(
                "OCR readings are missing or uncertain. Enter both values after "
                "checking them against the meter, or retake the photo."
            )
        final_current_fill = meter_photo.ocr_current_fill_litres
        final_cumulative_total = meter_photo.ocr_cumulative_total_litres
        manual_correction = False

    additional_warnings = _meter_reading_warnings(
        session,
        vehicle,
        current_fill_litres
        if current_fill_litres is not None
        else meter_photo.ocr_current_fill_litres,
        cumulative_total_litres
        if cumulative_total_litres is not None
        else meter_photo.ocr_cumulative_total_litres,
    )
    if additional_warnings:
        existing_warnings = list(meter_photo.ocr_warnings or [])
        meter_photo.ocr_warnings = list(
            dict.fromkeys(existing_warnings + additional_warnings)
        )

    now = datetime.now(timezone.utc)
    meter_photo.current_fill_litres = final_current_fill
    meter_photo.cumulative_total_litres = final_cumulative_total
    meter_photo.verified_at = now
    meter_photo.verified_by_employee_id = employee.id
    meter_photo.verification_method = (
        "manual_correction" if manual_correction else "ocr_confirmed"
    )
    return meter_photo
