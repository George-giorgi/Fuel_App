import math
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "diesel-desk-dev.sqlite"
METER_PHOTO_DIRECTORY = PROJECT_ROOT / "uploads" / "meter-photos"
SESSION_COOKIE_NAME = "diesel_desk_session"
ACCESS_TOKEN_MINUTES = 30
SESSION_COOKIE_SECURE = os.environ.get("FUEL_COOKIE_SECURE", "").lower() == "true"
METER_OCR_MIN_CONFIDENCE = 60.0


def get_meter_tolerance_litres() -> float:
    value = os.environ.get("FUEL_METER_TOLERANCE_LITRES", "0.10")
    try:
        tolerance = float(value)
    except ValueError as error:
        raise RuntimeError(
            "FUEL_METER_TOLERANCE_LITRES must be a non-negative number."
        ) from error
    if not math.isfinite(tolerance) or tolerance < 0:
        raise RuntimeError(
            "FUEL_METER_TOLERANCE_LITRES must be a non-negative number."
        )
    return tolerance


def get_auth_secret() -> str:
    secret = os.environ.get("FUEL_AUTH_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("FUEL_AUTH_SECRET must contain at least 32 characters.")
    return secret
