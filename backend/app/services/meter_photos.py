from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import logging
import math
import os
from pathlib import Path
import secrets
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from backend.app.core.config import METER_PHOTO_DIRECTORY
from backend.app.models import Employee, MeterPhoto, QrSession, Vehicle
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


QR_SESSION_MINUTES = 10
MAX_METER_PHOTO_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
PHOTO_TYPES = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png": ("PNG", ".png"),
}
logger = logging.getLogger(__name__)


class UnsupportedMeterPhotoType(ValueError):
    pass


class InvalidMeterPhoto(ValueError):
    pass


class InvalidQrSession(ValueError):
    pass


class InvalidMeterVerification(ValueError):
    pass


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


def _store_private_photo(content: bytes, extension: str) -> tuple[str, Path]:
    METER_PHOTO_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(METER_PHOTO_DIRECTORY, 0o700)
    storage_key = f"{secrets.token_hex(16)}{extension}"
    destination = METER_PHOTO_DIRECTORY / storage_key
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stored_file:
            stored_file.write(content)
    except OSError:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a partial meter photo.")
        raise
    return storage_key, destination


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
    storage_key, stored_path = _store_private_photo(content, extension)
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
    meter_photo.ocr_message = ocr_result.message
    qr_session.consumed_at = now
    add_meter_photo(session, meter_photo)

    return meter_photo, vehicle.registration_number


def verify_meter_photo(
    session: Session,
    employee: Employee,
    meter_photo_id: int,
) -> MeterPhoto | None:
    meter_photo = get_meter_photo_by_id(session, meter_photo_id)
    if meter_photo is None or meter_photo.employee_id != employee.id:
        return None
    if meter_photo.verified_at is not None:
        raise InvalidMeterVerification("This meter photo has already been verified.")
    vehicle = get_employee_vehicle(session, employee.id)
    if vehicle is None or vehicle.id != meter_photo.vehicle_id:
        return None
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
    ):
        raise InvalidMeterVerification(
            "OCR readings are missing or uncertain. Retake the photo; "
            "meter readings cannot be entered manually."
        )

    now = datetime.now(timezone.utc)
    meter_photo.current_fill_litres = meter_photo.ocr_current_fill_litres
    meter_photo.cumulative_total_litres = meter_photo.ocr_cumulative_total_litres
    meter_photo.verified_at = now
    meter_photo.verified_by_employee_id = employee.id
    meter_photo.verification_method = "ocr_confirmed"
    return meter_photo
