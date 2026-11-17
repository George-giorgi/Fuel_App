from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import secrets
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import is_manual_meter_entry_enabled
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
from backend.app.services.meter_readings import (
    InvalidMeterDigits,
    assess_meter_readings,
    decimal_to_milli_litres,
    milli_litres_to_decimal,
    parse_fill_raw_digits,
    parse_total_raw_digits,
)
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
    *,
    reading_mode: str = "ocr",
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
    if reading_mode not in {"ocr", "manual"}:
        raise InvalidMeterPhoto("Reading mode must be OCR or manual.")
    if reading_mode == "manual" and not is_manual_meter_entry_enabled():
        raise InvalidMeterPhoto("Manual meter entry is disabled by configuration.")
    if reading_mode == "manual":
        meter_photo.ocr_status = "skipped"
        meter_photo.ocr_message = "OCR skipped for manual entry."
        qr_session.consumed_at = now
        add_meter_photo(session, meter_photo)
        return meter_photo, vehicle.registration_number

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
    duplicate_photo = session.scalar(
        select(MeterPhoto.id).where(
            MeterPhoto.sha256 == meter_photo.sha256,
            MeterPhoto.id != meter_photo.id,
        )
    )
    warnings_found = list(ocr_result.warnings)
    if duplicate_photo is not None:
        warnings_found.append(
            "This photograph matches an earlier upload and requires review."
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
    current_fill_raw_digits: str | None = None,
    cumulative_total_raw_digits: str | None = None,
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
    if current_fill_raw_digits is None and current_fill_litres is not None:
        if (
            not current_fill_litres.is_finite()
            or current_fill_litres < 0
            or current_fill_litres.as_tuple().exponent < -3
        ):
            raise InvalidMeterVerification(
                "Fill must be non-negative with no more than 3 decimal places."
            )
        current_fill_raw_digits = str(int(current_fill_litres * 1000))
    if cumulative_total_raw_digits is None and cumulative_total_litres is not None:
        if (
            not cumulative_total_litres.is_finite()
            or cumulative_total_litres < 0
            or cumulative_total_litres.as_tuple().exponent < -3
        ):
            raise InvalidMeterVerification(
                "Global cumulative total must be non-negative with no more than 3 decimals."
            )
        cumulative_total_raw_digits = str(
            decimal_to_milli_litres(cumulative_total_litres)
        )
    if current_fill_raw_digits is None and meter_photo.ocr_status == "ready":
        if (meter_photo.ocr_current_fill_confidence or 0) >= 60:
            current_fill_raw_digits = meter_photo.ocr_current_fill_raw_digits
    if cumulative_total_raw_digits is None and meter_photo.ocr_status == "ready":
        if (meter_photo.ocr_cumulative_total_confidence or 0) >= 60:
            cumulative_total_raw_digits = (
                meter_photo.ocr_cumulative_total_raw_digits
            )
    try:
        fill_milli_litres = parse_fill_raw_digits(current_fill_raw_digits)
        cumulative_total = parse_total_raw_digits(cumulative_total_raw_digits)
    except InvalidMeterDigits as error:
        raise InvalidMeterVerification(str(error)) from error
    if cumulative_total is None:
        raise InvalidMeterVerification(
            "The global cumulative total is missing. Check the TOTAL row and enter its digits."
        )
    global_meter = session.get(GlobalMeterState, 1)
    previous_total = (
        global_meter.current_total_integer
        if global_meter is not None
        else None
    )
    ocr_values_match = (
        meter_photo.ocr_status == "ready"
        and current_fill_raw_digits
        == meter_photo.ocr_current_fill_raw_digits
        and cumulative_total_raw_digits
        == meter_photo.ocr_cumulative_total_raw_digits
    )
    if not ocr_values_match:
        source = "MANUAL"
    elif meter_photo.ocr_provider == "google_vision":
        source = "GOOGLE_VISION"
    elif meter_photo.ocr_provider == "tesseract":
        source = "OPENCV"
    else:
        raise InvalidMeterVerification(
            "The OCR provider is unsupported for verified reading sources."
        )
    if meter_photo.ocr_status == "skipped" and not is_manual_meter_entry_enabled():
        raise InvalidMeterVerification(
            "Manual meter entry is disabled by configuration."
        )
    assessment = assess_meter_readings(
        fill_milli_litres=fill_milli_litres,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=cumulative_total,
        source=source,
        tank_capacity_litres=vehicle.tank_capacity,
    )
    evidence_warnings = list(meter_photo.ocr_warnings or [])
    for label, numeric_value, raw_digits in (
        (
            "current-fill",
            meter_photo.ocr_current_fill_litres,
            meter_photo.ocr_current_fill_raw_digits,
        ),
        (
            "global-total",
            meter_photo.ocr_cumulative_total_litres,
            meter_photo.ocr_cumulative_total_raw_digits,
        ),
    ):
        if numeric_value is None and raw_digits is None:
            continue
        if raw_digits is None:
            evidence_warnings.append(
                f"OCR {label} has no raw-digit evidence and requires review."
            )
        elif not raw_digits.isascii() or not raw_digits.isdigit():
            evidence_warnings.append(
                f"OCR {label} contains invalid raw digits and requires review."
            )
        elif (
            numeric_value is None
            or Decimal(str(numeric_value))
            != (
                Decimal(int(raw_digits))
                if label == "current-fill"
                else Decimal(int(raw_digits)).scaleb(-3)
            )
        ):
            evidence_warnings.append(
                f"OCR {label} numeric result disagrees with its raw digits."
            )
    current_fill_litres = milli_litres_to_decimal(
        assessment.fill_milli_litres
    )
    final_current_fill = (
        float(current_fill_litres)
        if current_fill_litres is not None
        else None
    )
    final_cumulative_total = (
        float(milli_litres_to_decimal(cumulative_total))
        if cumulative_total is not None
        else None
    )

    now = datetime.now(timezone.utc)
    meter_photo.current_fill_milli_litres = assessment.fill_milli_litres
    meter_photo.top_current_fill_milli_litres = (
        assessment.top_current_fill_milli_litres
    )
    meter_photo.cumulative_total_integer = cumulative_total
    meter_photo.previous_global_total_integer = previous_total
    meter_photo.current_fill_raw_digits = current_fill_raw_digits
    meter_photo.cumulative_total_raw_digits = cumulative_total_raw_digits
    meter_photo.reading_source = assessment.source
    meter_photo.fill_source = assessment.fill_source
    meter_photo.fill_calculation = assessment.fill_calculation
    meter_photo.reconciliation_status = assessment.reconciliation_status
    meter_photo.ocr_warnings = list(
        dict.fromkeys(
            evidence_warnings
            + list(assessment.warnings)
        )
    )
    meter_photo.current_fill_litres = final_current_fill
    meter_photo.cumulative_total_litres = final_cumulative_total
    meter_photo.verified_at = now
    meter_photo.verified_by_employee_id = employee.id
    meter_photo.verification_method = assessment.source
    return meter_photo
