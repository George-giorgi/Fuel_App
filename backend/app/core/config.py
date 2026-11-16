import math
import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "diesel-desk-dev.sqlite"
METER_PHOTO_DIRECTORY = PROJECT_ROOT / "uploads" / "meter-photos"
SESSION_COOKIE_NAME = "diesel_desk_session"
ACCESS_TOKEN_MINUTES = 30
SESSION_COOKIE_SECURE = os.environ.get("FUEL_COOKIE_SECURE", "").lower() == "true"
SESSION_COOKIE_SAMESITE = os.environ.get("FUEL_COOKIE_SAMESITE", "strict").lower()
METER_OCR_MIN_CONFIDENCE = 60.0


def _parse_database_url(configured_url: str) -> URL:
    if not configured_url:
        return URL.create("sqlite", database=str(DATABASE_PATH))

    url = make_url(configured_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url


def get_database_url() -> URL:
    return _parse_database_url(os.environ.get("DATABASE_URL", "").strip())


def get_migration_database_url() -> URL:
    configured_url = os.environ.get("DATABASE_URL_UNPOOLED", "").strip()
    if not configured_url:
        return get_database_url()
    return _parse_database_url(configured_url)


def get_cors_origins() -> list[str]:
    origins = [
        origin.strip().rstrip("/")
        for origin in os.environ.get("FUEL_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("FUEL_CORS_ORIGINS must not contain a wildcard.")
    return origins


def validate_cookie_settings() -> None:
    if SESSION_COOKIE_SAMESITE not in {"strict", "lax", "none"}:
        raise RuntimeError(
            "FUEL_COOKIE_SAMESITE must be 'strict', 'lax', or 'none'."
        )
    if SESSION_COOKIE_SAMESITE == "none" and not SESSION_COOKIE_SECURE:
        raise RuntimeError(
            "FUEL_COOKIE_SECURE=true is required when FUEL_COOKIE_SAMESITE=none."
        )
    if (
        os.environ.get("FUEL_ENV", "").lower() == "production"
        and not get_cors_origins()
    ):
        raise RuntimeError(
            "Set FUEL_CORS_ORIGINS to the exact production frontend origin."
        )


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
