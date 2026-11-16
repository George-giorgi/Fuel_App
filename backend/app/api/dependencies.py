from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.config import SESSION_COOKIE_NAME
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.services.employee_sessions import get_employee_for_session


def get_current_employee(
    session: Annotated[Session, Depends(get_db_session)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Employee:
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    employee = get_employee_for_session(session, token)
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return employee


def require_admin(
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> Employee:
    if employee.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return employee


def require_management(
    employee: Annotated[Employee, Depends(get_current_employee)],
) -> Employee:
    if employee.role not in {"admin", "boss"}:
        raise HTTPException(status_code=403, detail="Management access required.")
    return employee
