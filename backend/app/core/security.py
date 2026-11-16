from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from backend.app.core.config import ACCESS_TOKEN_MINUTES, get_auth_secret


password_hasher = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-account-password")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    encoded_hash = password_hash or _DUMMY_PASSWORD_HASH
    is_valid = password_hasher.verify(password, encoded_hash)
    return is_valid and password_hash is not None


def create_access_token(employee_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(employee_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, get_auth_secret(), algorithm="HS256")


def decode_access_token(token: str) -> int:
    payload = jwt.decode(
        token,
        get_auth_secret(),
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp"]},
    )
    return int(payload["sub"])
