from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.models import Employee, EmployeeSession, FuelRecord


class InvalidAdminDateRange(ValueError):
    pass


class AdminEmployeeNotFound(LookupError):
    pass


def list_admin_employees(session: Session) -> list[Employee]:
    return list(
        session.scalars(
            select(Employee).order_by(Employee.name.collate("NOCASE"), Employee.id)
        ).all()
    )


def update_employee_role(
    session: Session, employee_id: int, role: Literal["employee", "boss"]
) -> Employee | None:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.role == "admin":
        return None
    employee.role = role
    session.flush()
    return employee


def update_employee_status(
    session: Session, employee_id: int, is_active: bool
) -> Employee | None:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.role == "admin":
        return None
    employee.is_active = is_active
    if not is_active:
        revoked_at = datetime.now(timezone.utc)
        active_sessions = session.scalars(
            select(EmployeeSession).where(
                EmployeeSession.employee_id == employee_id,
                EmployeeSession.revoked_at.is_(None),
            )
        )
        for employee_session in active_sessions:
            employee_session.revoked_at = revoked_at
    session.flush()
    return employee


def list_employee_fuel_records(
    session: Session,
    employee_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[FuelRecord]:
    if session.get(Employee, employee_id) is None:
        raise AdminEmployeeNotFound("Employee not found.")
    conditions = [FuelRecord.employee_id == employee_id]
    conditions.extend(_date_conditions(start_date, end_date))
    return list(
        session.scalars(
            select(FuelRecord)
            .where(*conditions)
            .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        ).all()
    )


def get_admin_fuel_summary(
    session: Session,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    conditions = _date_conditions(start_date, end_date)
    fill_litres = func.coalesce(
        FuelRecord.current_fill_litres, FuelRecord.litres
    )
    totals = session.execute(
        select(
            func.count(FuelRecord.id),
            func.coalesce(func.sum(fill_litres), 0.0),
            func.coalesce(func.sum(FuelRecord.cost), 0.0),
            func.count(case((FuelRecord.cost > 0, 1))),
        ).where(*conditions)
    ).one()
    available = session.execute(
        select(func.min(FuelRecord.created_at), func.max(FuelRecord.created_at))
    ).one()
    vehicle_fill_sum = func.sum(fill_litres)
    top_vehicles = session.execute(
        select(
            FuelRecord.vehicle_id,
            FuelRecord.reg_number,
            vehicle_fill_sum,
            func.count(FuelRecord.id),
        )
        .where(*conditions)
        .group_by(FuelRecord.vehicle_id, FuelRecord.reg_number)
        .order_by(
            vehicle_fill_sum.desc(),
            func.count(FuelRecord.id).desc(),
            FuelRecord.reg_number,
        )
        .limit(10)
    ).all()
    return {
        "available_from": available[0].date() if available[0] is not None else None,
        "available_to": available[1].date() if available[1] is not None else None,
        "start_date": start_date,
        "end_date": end_date,
        "fill_count": int(totals[0]),
        "total_fill_litres": float(totals[1]),
        "total_cost": float(totals[2]),
        "cost_record_count": int(totals[3]),
        "top_vehicles": [
            {
                "vehicle_id": row[0],
                "registration_number": row[1],
                "total_fill_litres": float(row[2]),
                "fill_count": int(row[3]),
            }
            for row in top_vehicles
        ],
    }


def _date_conditions(
    start_date: date | None, end_date: date | None
) -> list[Any]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidAdminDateRange("Start date must not be after end date.")
    conditions = []
    if start_date is not None:
        conditions.append(
            FuelRecord.created_at
            >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )
    if end_date is not None:
        end_exclusive = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
        conditions.append(FuelRecord.created_at < end_exclusive)
    return conditions
