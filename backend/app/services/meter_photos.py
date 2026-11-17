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
    parse_total_raw_digits,
)
from backend.app.services.photo_storage import read_photo, store_photo


QR_SESSION_MINUTES = 10
MAX_METER_PHOTO_BYTES = 10 * 1024 * 1024
MAX_METER_OCR_PHOTO_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_METER_OCR_MESSAGE_LENGTH = 255
_HEIF_BRANDS = {
    b"heic",
    b"heix",
    b"hevc",
    b"hevx",
    b"heis",
    b"heim",
    b"hevm",
    b"hevs",
    b"mif1",
    b"msf1",
}
_AVIF_BRANDS = {b"avif", b"avis"}
_PHOTO_FORMAT_EXTENSIONS = {"JPEG": ".jpg", "TIFF": ".tiff"}


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
    if employee.role == "boss":
        vehicle = get_vehicle_by_id(session, vehicle_id)
    else:
        vehicle = get_employee_vehicle(session, employee.id)
        if vehicle is None or vehicle.id != vehicle_id:
            return None
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


def _inspect_meter_photo(
    content: bytes,
    content_type: str | None,
) -> tuple[str, str]:
    brands = set()
    if len(content) >= 16 and content[4:8] == b"ftyp":
        brands.add(content[8:12])
        brands.update(
            content[offset : offset + 4]
            for offset in range(16, min(len(content) - 3, 64), 4)
        )
    if brands & _AVIF_BRANDS:
        return ".avif", "image/avif"
    if brands & _HEIF_BRANDS:
        if (content_type or "").lower() == "image/heif":
            return ".heif", "image/heif"
        return ".heic", "image/heic"
    if (content_type or "").lower() in {"image/heic", "image/heif"}:
        raise InvalidMeterPhoto("The uploaded HEIC photo is not valid.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidMeterPhoto("The image dimensions are too large.")
                image_format = image.format
                if image_format is None:
                    raise InvalidMeterPhoto("The uploaded file is not a valid image.")
                image.verify()
    except InvalidMeterPhoto:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as error:
        raise UnsupportedMeterPhotoType(
            "The photo format is not supported by the image decoder."
        ) from error

    media_type = Image.MIME.get(image_format)
    if media_type is not None and not media_type.startswith("image/"):
        raise UnsupportedMeterPhotoType("Upload a photo image, not a document or video.")
    if media_type is None:
        media_type = f"image/{image_format.lower()}"
    extension = _PHOTO_FORMAT_EXTENSIONS.get(image_format)
    if extension is None:
        extension = next(
            (
                registered_extension
                for registered_extension, registered_format
                in Image.registered_extensions().items()
                if registered_format == image_format
            ),
            None,
        )
    if extension is None:
        raise UnsupportedMeterPhotoType("The photo extension is not supported.")
    return extension, media_type


def validate_meter_photo(content: bytes, content_type: str | None) -> str:
    extension, _ = _inspect_meter_photo(content, content_type)
    return extension


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
    if reading_mode not in {"ocr", "manual"}:
        raise InvalidMeterPhoto("Reading mode must be OCR or manual.")
    if reading_mode == "manual" and not is_manual_meter_entry_enabled():
        raise InvalidMeterPhoto("Manual meter entry is disabled by configuration.")

    extension, normalized_content_type = _inspect_meter_photo(
        content,
        content_type,
    )
    photo_hash = sha256(content).hexdigest()
    existing_photo = session.scalar(
        select(MeterPhoto).where(MeterPhoto.qr_session_id == qr_session.id)
    )
    if existing_photo is not None:
        if (
            existing_photo.employee_id == employee.id
            and existing_photo.sha256 == photo_hash
            and (
                (reading_mode == "manual" and existing_photo.ocr_status == "skipped")
                or (reading_mode == "ocr" and existing_photo.ocr_status != "skipped")
            )
        ):
            vehicle = get_vehicle_by_id(session, qr_session.vehicle_id)
            if vehicle is not None:
                return existing_photo, vehicle.registration_number
        raise InvalidQrSession(
            "This upload session already contains a different meter photo."
        )

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

    storage_key, stored_path = store_photo(
        content,
        extension,
        normalized_content_type,
    )
    if stored_path is not None:
        session.info.setdefault("rollback_upload_paths", []).append(stored_path)

    meter_photo = MeterPhoto(
        qr_session_id=qr_session.id,
        employee_id=employee.id,
        vehicle_id=qr_session.vehicle_id,
        storage_key=storage_key,
        content_type=normalized_content_type,
        size_bytes=len(content),
        sha256=photo_hash,
        uploaded_at=now,
    )
    if reading_mode == "manual":
        meter_photo.ocr_status = "skipped"
        meter_photo.ocr_message = "OCR skipped for manual entry."
        qr_session.consumed_at = now
        add_meter_photo(session, meter_photo)
        return meter_photo, vehicle.registration_number

    meter_photo.ocr_status = "pending"
    qr_session.consumed_at = now
    duplicate_photo = session.scalar(
        select(MeterPhoto.id).where(
            MeterPhoto.sha256 == meter_photo.sha256,
            MeterPhoto.id != meter_photo.id,
        )
    )
    if duplicate_photo is not None:
        meter_photo.ocr_warnings = [
            "This photograph matches an earlier upload and requires review."
        ]
    add_meter_photo(session, meter_photo)
    return meter_photo, vehicle.registration_number


def recognize_uploaded_meter_photo(
    session: Session,
    employee: Employee,
    meter_photo_id: int,
    processing_content: bytes | None = None,
    processing_content_type: str | None = None,
) -> MeterPhoto | None:
    meter_photo = session.scalar(
        select(MeterPhoto)
        .where(MeterPhoto.id == meter_photo_id)
        .with_for_update()
    )
    if meter_photo is None or meter_photo.employee_id != employee.id:
        return None
    if meter_photo.ocr_status in {"ready", "uncertain", "skipped"}:
        return meter_photo
    if meter_photo.verified_at is not None:
        return meter_photo

    content = read_photo(meter_photo.storage_key)
    if content is None:
        meter_photo.ocr_status = "failed"
        meter_photo.ocr_message = "The stored photo is unavailable; upload it again."
        return meter_photo

    ocr_content = content
    if processing_content is not None:
        if len(processing_content) > MAX_METER_OCR_PHOTO_BYTES:
            raise InvalidMeterPhoto("The optimized OCR photo must be 8 MB or smaller.")
        processing_extension, _ = _inspect_meter_photo(
            processing_content,
            processing_content_type,
        )
        if processing_extension not in {".jpg", ".png"}:
            raise InvalidMeterPhoto(
                "The optimized OCR photo must be JPEG or PNG."
            )
        ocr_content = processing_content

    meter_photo.ocr_status = "processing"
    ocr_result = extract_meter_readings(ocr_content)
    meter_photo.ocr_status = ocr_result.status
    meter_photo.ocr_cumulative_total_litres = ocr_result.cumulative_total_litres
    meter_photo.ocr_cumulative_total_confidence = (
        ocr_result.cumulative_total_confidence
    )
    meter_photo.ocr_message = (
        ocr_result.message[:MAX_METER_OCR_MESSAGE_LENGTH]
        if ocr_result.message is not None
        else None
    )
    meter_photo.ocr_provider = ocr_result.provider
    meter_photo.ocr_cumulative_total_raw_digits = (
        ocr_result.cumulative_total_raw_digits
    )
    meter_photo.ocr_cumulative_total_segment_raw_digits = (
        ocr_result.cumulative_total_segment_raw_digits
    )
    meter_photo.suggested_cumulative_total_raw_digits = (
        ocr_result.cumulative_total_suggested_raw_digits
    )
    meter_photo.ocr_cumulative_total_decimal_position = (
        ocr_result.cumulative_total_decimal_position
    )
    meter_photo.ocr_cumulative_total_segment_confidence = (
        ocr_result.cumulative_total_segment_confidence
    )
    existing_warnings = meter_photo.ocr_warnings or []
    meter_photo.ocr_warnings = list(
        dict.fromkeys([*existing_warnings, *ocr_result.warnings])
    )
    return meter_photo


def verify_meter_photo(
    session: Session,
    employee: Employee,
    meter_photo_id: int,
    cumulative_total_litres: Decimal | None = None,
    cumulative_total_raw_digits: str | None = None,
) -> MeterPhoto | None:
    meter_photo = get_meter_photo_by_id(session, meter_photo_id)
    if meter_photo is None or meter_photo.employee_id != employee.id:
        return None
    vehicle = get_vehicle_by_id(session, meter_photo.vehicle_id)
    if vehicle is None:
        return None
    if employee.role != "boss":
        assigned_vehicle = get_employee_vehicle(session, employee.id)
        if assigned_vehicle is None or assigned_vehicle.id != vehicle.id:
            return None
    if cumulative_total_raw_digits is None and cumulative_total_litres is not None:
        if (
            not cumulative_total_litres.is_finite()
            or cumulative_total_litres < 0
            or cumulative_total_litres.as_tuple().exponent < -3
            or cumulative_total_litres > Decimal("999.999")
        ):
            raise InvalidMeterVerification(
                "Global cumulative total must fit exactly six meter digits."
            )
        cumulative_total_raw_digits = str(
            decimal_to_milli_litres(cumulative_total_litres)
        ).zfill(6)
    if cumulative_total_raw_digits is None and meter_photo.ocr_status == "ready":
        if (meter_photo.ocr_cumulative_total_confidence or 0) >= 60:
            cumulative_total_raw_digits = (
                meter_photo.suggested_cumulative_total_raw_digits
                or meter_photo.ocr_cumulative_total_raw_digits
            )
    try:
        cumulative_total = parse_total_raw_digits(cumulative_total_raw_digits)
    except InvalidMeterDigits as error:
        raise InvalidMeterVerification(str(error)) from error
    if cumulative_total is None:
        raise InvalidMeterVerification(
            "The global cumulative total is missing. Check the TOTAL row and enter its digits."
        )
    if cumulative_total_raw_digits is None or len(cumulative_total_raw_digits) != 6:
        raise InvalidMeterVerification(
            "The TOTAL reading must contain exactly six digits. Check for missing or extra digits."
        )
    if meter_photo.verified_at is not None:
        if cumulative_total_raw_digits == meter_photo.cumulative_total_raw_digits:
            return meter_photo
        raise InvalidMeterVerification(
            "This meter photo was already confirmed with a different TOTAL reading."
        )
    global_meter = session.get(GlobalMeterState, 1)
    previous_total = (
        global_meter.current_total_integer
        if global_meter is not None
        else None
    )
    ocr_values_match = (
        meter_photo.ocr_status == "ready"
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
        fill_milli_litres=None,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=cumulative_total,
        source=source,
    )
    reading_warnings = list(meter_photo.ocr_warnings or [])
    reading_warnings.extend(assessment.warnings)
    manually_corrected = (
        cumulative_total_raw_digits
        != meter_photo.ocr_cumulative_total_raw_digits
    )
    if manually_corrected:
        reading_warnings.append(
            "The employee corrected or manually entered the OCR-suggested TOTAL digits."
        )
    reading_warnings = list(dict.fromkeys(reading_warnings))
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
    meter_photo.top_current_fill_milli_litres = None
    meter_photo.cumulative_total_integer = cumulative_total
    meter_photo.previous_global_total_integer = previous_total
    meter_photo.current_fill_raw_digits = None
    meter_photo.cumulative_total_raw_digits = cumulative_total_raw_digits
    meter_photo.reading_source = assessment.source
    meter_photo.fill_source = assessment.fill_source
    meter_photo.fill_calculation = assessment.fill_calculation
    meter_photo.reconciliation_status = assessment.reconciliation_status
    meter_photo.reading_warnings = reading_warnings
    meter_photo.cumulative_total_manually_corrected = manually_corrected
    meter_photo.current_fill_litres = final_current_fill
    meter_photo.cumulative_total_litres = final_cumulative_total
    meter_photo.verified_at = now
    meter_photo.verified_by_employee_id = employee.id
    meter_photo.verification_method = assessment.source
    return meter_photo
