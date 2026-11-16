from typing import Literal

from sqlalchemy.orm import Session

from backend.app.core.security import hash_password, verify_password
from backend.app.models import Employee
from backend.app.repositories.employees import (
    add_employee,
    get_employee_by_email,
    get_employee_by_login,
    has_admin_employee,
)


def authenticate_employee(
    session: Session, identifier: str, password: str
) -> Employee | None:
    employee = get_employee_by_login(session, identifier)
    if employee is None or not employee.is_active:
        verify_password(password, None)
        return None
    if not verify_password(password, employee.password_hash):
        return None
    return employee


def create_employee(
    session: Session,
    email: str,
    name: str,
    password: str,
    role: Literal["employee", "boss"] = "employee",
) -> Employee:
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters.")
    employee = Employee(
        email=email.lower(),
        name=name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    return add_employee(session, employee)


def bootstrap_admin(
    session: Session, email: str, name: str, password: str
) -> Employee:
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters.")
    if not name.strip():
        raise ValueError("The administrator name must not be empty.")
    if has_admin_employee(session):
        raise ValueError("An administrator already exists.")
    if get_employee_by_email(session, email.lower()) is not None:
        raise ValueError("The specified admin email already exists.")
    admin = Employee(
        email=email.lower(),
        name=name.strip(),
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
    )
    return add_employee(session, admin)
