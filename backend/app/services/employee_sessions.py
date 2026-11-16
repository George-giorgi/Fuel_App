from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import ACCESS_TOKEN_MINUTES
from backend.app.models import Employee, EmployeeSession


def create_employee_session(session: Session, employee: Employee) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    session.add(
        EmployeeSession(
            employee_id=employee.id,
            token_hash=sha256(token.encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        )
    )
    session.flush()
    return token


def _session_for_token(session: Session, token: str) -> EmployeeSession | None:
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    return session.scalar(
        select(EmployeeSession).where(EmployeeSession.token_hash == token_hash)
    )


def get_employee_for_session(session: Session, token: str) -> Employee | None:
    employee_session = _session_for_token(session, token)
    if employee_session is None or employee_session.revoked_at is not None:
        return None

    expires_at = employee_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return employee_session.employee


def revoke_employee_session(session: Session, token: str) -> None:
    employee_session = _session_for_token(session, token)
    if employee_session is not None and employee_session.revoked_at is None:
        employee_session.revoked_at = datetime.now(timezone.utc)
        session.flush()
