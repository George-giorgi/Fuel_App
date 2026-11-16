import logging
import os
from functools import lru_cache
import secrets
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from backend.app.core.config import METER_PHOTO_DIRECTORY


logger = logging.getLogger(__name__)


class PhotoStorageError(RuntimeError):
    pass


class PhotoStorageConfigurationError(PhotoStorageError):
    pass


def get_photo_storage_backend() -> str:
    backend = os.environ.get("FUEL_PHOTO_STORAGE", "local").strip().lower()
    if backend not in {"local", "r2"}:
        raise PhotoStorageConfigurationError(
            "FUEL_PHOTO_STORAGE must be either 'local' or 'r2'."
        )
    return backend


def validate_photo_storage_configuration() -> None:
    backend = get_photo_storage_backend()
    if os.environ.get("FUEL_ENV", "").lower() == "production" and backend != "r2":
        raise PhotoStorageConfigurationError(
            "FUEL_PHOTO_STORAGE=r2 is required in production."
        )
    if backend == "r2":
        _r2_bucket_name()
        _r2_client()


def _r2_bucket_name() -> str:
    bucket_name = os.environ.get("R2_BUCKET_NAME", "").strip()
    if not bucket_name:
        raise PhotoStorageConfigurationError(
            "R2_BUCKET_NAME is required when FUEL_PHOTO_STORAGE=r2."
        )
    return bucket_name


@lru_cache(maxsize=1)
def _r2_client():
    account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if not account_id or not access_key or not secret_key:
        raise PhotoStorageConfigurationError(
            "R2_ACCOUNT_ID, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY are "
            "required when FUEL_PHOTO_STORAGE=r2."
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def _store_local_photo(content: bytes, storage_key: str) -> Path:
    METER_PHOTO_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(METER_PHOTO_DIRECTORY, 0o700)
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
    return destination


def store_photo(
    content: bytes, extension: str, content_type: str
) -> tuple[str, Path | None]:
    storage_key = f"{secrets.token_hex(16)}{extension}"
    if get_photo_storage_backend() == "local":
        try:
            return storage_key, _store_local_photo(content, storage_key)
        except OSError as error:
            raise PhotoStorageError("Could not store the uploaded meter photo.") from error

    try:
        response = _r2_client().put_object(
            Bucket=_r2_bucket_name(),
            Key=storage_key,
            Body=content,
            ContentType=content_type,
        )
    except PhotoStorageError:
        raise
    except (BotoCoreError, ClientError, OSError) as error:
        raise PhotoStorageError("Could not store the uploaded meter photo in R2.") from error

    status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status_code is None or not 200 <= status_code < 300:
        raise PhotoStorageError(
            "R2 did not confirm that the uploaded meter photo was stored."
        )
    return storage_key, None


def read_photo(storage_key: str) -> bytes | None:
    if not storage_key or Path(storage_key).name != storage_key:
        raise PhotoStorageError("The stored meter photo reference is invalid.")

    if get_photo_storage_backend() == "local":
        directory = METER_PHOTO_DIRECTORY.resolve()
        path = (directory / storage_key).resolve()
        if path.parent != directory:
            raise PhotoStorageError("The stored meter photo reference is invalid.")
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise PhotoStorageError("Could not read the stored meter photo.") from error

    try:
        response = _r2_client().get_object(
            Bucket=_r2_bucket_name(),
            Key=storage_key,
        )
    except ClientError as error:
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise PhotoStorageError("Could not retrieve the stored meter photo from R2.") from error
    except (BotoCoreError, OSError) as error:
        raise PhotoStorageError("Could not retrieve the stored meter photo from R2.") from error

    body = response.get("Body")
    if body is None:
        raise PhotoStorageError("R2 returned an invalid meter photo response.")
    try:
        return body.read()
    except (BotoCoreError, OSError) as error:
        raise PhotoStorageError("Could not read the stored meter photo from R2.") from error
    finally:
        body.close()


def delete_photo(storage_key: str) -> None:
    if not storage_key or Path(storage_key).name != storage_key:
        raise PhotoStorageError("The stored meter photo reference is invalid.")

    if get_photo_storage_backend() == "local":
        directory = METER_PHOTO_DIRECTORY.resolve()
        path = (directory / storage_key).resolve()
        if path.parent != directory:
            raise PhotoStorageError("The stored meter photo reference is invalid.")
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise PhotoStorageError("Could not delete the stored meter photo.") from error
        return

    try:
        response = _r2_client().delete_object(
            Bucket=_r2_bucket_name(),
            Key=storage_key,
        )
    except (BotoCoreError, ClientError, OSError) as error:
        raise PhotoStorageError("Could not delete the stored meter photo from R2.") from error

    status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if status_code is not None and not 200 <= status_code < 300:
        raise PhotoStorageError("R2 did not confirm that the meter photo was deleted.")
