from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.models import Employee


def get_employee_by_email(session: Session, email: str) -> Employee | None:
    return session.scalar(select(Employee).where(Employee.email == email))


def get_employee_by_login(session: Session, identifier: str) -> Employee | None:
    normalized_identifier = identifier.strip().lower()
    return session.scalar(
        select(Employee).where(
            or_(
                func.lower(Employee.email) == normalized_identifier,
                func.lower(Employee.username) == normalized_identifier,
            )
        )
    )


def get_employee_by_id(session: Session, employee_id: int) -> Employee | None:
    return session.get(Employee, employee_id)


def has_admin_employee(session: Session) -> bool:
    return session.scalar(
        select(Employee.id).where(Employee.role == "admin").limit(1)
    ) is not None


def add_employee(session: Session, employee: Employee) -> Employee:
    session.add(employee)
    session.flush()
    return employee
