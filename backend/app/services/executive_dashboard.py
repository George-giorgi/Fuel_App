from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.config import METER_OCR_MIN_CONFIDENCE
from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterState,
    MeterPhoto,
    Vehicle,
)
from backend.app.services.nct import _nct_status, get_irish_today


IRELAND_TIME_ZONE = ZoneInfo("Europe/Dublin")
FILL_LITRES = func.coalesce(
    FuelRecord.current_fill_litres, FuelRecord.litres
)


def get_executive_overview(
    session: Session, *, include_demo: bool = False
) -> dict[str, Any]:
    today = get_irish_today()
    month_start = today.replace(day=1)
    today_summary = _period_summary(
        session, today, today + timedelta(days=1), include_demo=include_demo
    )
    month_summary = _period_summary(
        session, month_start, today + timedelta(days=1), include_demo=include_demo
    )

    vehicles = list(
        session.scalars(
            select(Vehicle)
            .options(selectinload(Vehicle.employees))
            .where(
                Vehicle.is_company_vehicle.is_(True),
                *_vehicle_demo_conditions(include_demo),
            )
        ).all()
    )
    active_count = sum(vehicle.is_active for vehicle in vehicles)
    nct_alerts: list[dict[str, Any]] = []
    valid_count = expiring_count = expired_count = missing_date_count = 0
    for vehicle in vehicles:
        status, days_remaining = _nct_status(vehicle.nct_expiry_date, today)
        if status == "not_set":
            missing_date_count += 1
        elif status == "expired":
            expired_count += 1
        elif status in {"upcoming", "urgent", "expires_today"}:
            expiring_count += 1
        else:
            valid_count += 1
        if status in {"upcoming", "urgent", "expires_today", "expired"}:
            nct_alerts.append(
                {
                    "vehicle_id": vehicle.id,
                    "registration_number": vehicle.registration_number,
                    "employee_names": sorted(
                        employee.name for employee in vehicle.employees
                    ),
                    "nct_expiry_date": vehicle.nct_expiry_date,
                    "days_remaining": days_remaining,
                    "status": status,
                }
            )
    nct_alerts.sort(
        key=lambda alert: (
            alert["nct_expiry_date"] or date.max,
            alert["registration_number"],
        )
    )

    latest_activity = _latest_transactions(
        session, limit=6, include_demo=include_demo
    )
    review_count = int(
        session.scalar(
            select(func.count(FuelRecord.id))
            .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
            .where(
                *_company_vehicle_conditions(include_demo=include_demo),
                *_fuel_record_demo_conditions(include_demo),
                FuelRecord.meter_check_status == "discrepancy",
            )
        )
        or 0
    )
    low_confidence_count = int(
        session.scalar(
            select(func.count(MeterPhoto.id))
            .join(Vehicle, Vehicle.id == MeterPhoto.vehicle_id)
            .where(
                *_company_vehicle_conditions(include_demo=include_demo),
                or_(
                    MeterPhoto.ocr_current_fill_confidence
                    < METER_OCR_MIN_CONFIDENCE,
                    MeterPhoto.ocr_cumulative_total_confidence
                    < METER_OCR_MIN_CONFIDENCE,
                ),
            )
        )
        or 0
    )

    meter = _global_meter_summary(
        session,
        review_count,
        low_confidence_count,
        include_demo=include_demo,
    )
    notifications = _notifications(
        session,
        nct_alerts,
        missing_date_count,
        month_summary["missing_cost_count"],
        today,
        include_demo=include_demo,
    )
    return {
        "today": today,
        "fleet": {
            "total_vehicles": len(vehicles),
            "active_vehicles": active_count,
            "inactive_vehicles": len(vehicles) - active_count,
        },
        "today_summary": today_summary,
        "month_summary": month_summary,
        "meter": meter,
        "nct": {
            "valid_count": valid_count,
            "expiring_count": expiring_count,
            "expired_count": expired_count,
            "missing_date_count": missing_date_count,
            "alerts": nct_alerts[:10],
        },
        "latest_activity": latest_activity,
        "notifications": notifications,
    }


def get_executive_analytics(
    session: Session, range_days: int = 30, *, include_demo: bool = False
) -> dict[str, Any]:
    today = get_irish_today()
    start_date = today - timedelta(days=range_days - 1)
    start_at, end_at = _date_bounds(start_date, today + timedelta(days=1))
    labels = [start_date + timedelta(days=offset) for offset in range(range_days)]
    litres_by_day = {label: 0.0 for label in labels}
    cost_by_day = {label: 0.0 for label in labels}
    cost_count_by_day = {label: 0 for label in labels}
    transaction_count_by_day = {label: 0 for label in labels}

    rows = session.execute(
        select(
            FuelRecord.created_at,
            FuelRecord.fuel_type,
            FILL_LITRES,
            FuelRecord.cost,
        )
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(
            *_company_vehicle_conditions(include_demo=include_demo),
            *_fuel_record_demo_conditions(include_demo),
            FuelRecord.created_at >= start_at,
            FuelRecord.created_at < end_at,
        )
    ).all()
    for created_at, fuel_type, fill_litres, cost in rows:
        timestamp = (
            created_at.replace(tzinfo=timezone.utc)
            if created_at.tzinfo is None
            else created_at
        )
        bucket = timestamp.astimezone(IRELAND_TIME_ZONE).date()
        if bucket not in litres_by_day:
            continue
        if fuel_type == "Diesel":
            litres_by_day[bucket] += float(fill_litres or 0)
        if cost > 0:
            cost_by_day[bucket] += float(cost)
            cost_count_by_day[bucket] += 1
        transaction_count_by_day[bucket] += 1

    top_vehicles, lowest_vehicles = _vehicle_usage(
        session, start_at, end_at, include_demo=include_demo
    )
    return {
        "range_days": range_days,
        "start_date": start_date,
        "end_date": today,
        "labels": labels,
        "diesel_litres": [litres_by_day[label] for label in labels],
        "fuel_cost_eur": [cost_by_day[label] for label in labels],
        "cost_record_count": [cost_count_by_day[label] for label in labels],
        "transaction_count": [
            transaction_count_by_day[label] for label in labels
        ],
        "top_vehicles": top_vehicles,
        "lowest_vehicles": lowest_vehicles,
    }


def list_executive_vehicles(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: str = "all",
    nct: str = "all",
    sort_by: str = "registration",
    sort_order: str = "asc",
    include_demo: bool = False,
) -> dict[str, Any]:
    today = get_irish_today()
    latest_activity = (
        select(FuelRecord.created_at)
        .where(
            FuelRecord.vehicle_id == Vehicle.id,
            *_fuel_record_demo_conditions(include_demo),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    latest_mileage = (
        select(FuelRecord.mileage_miles)
        .where(
            FuelRecord.vehicle_id == Vehicle.id,
            *_fuel_record_demo_conditions(include_demo),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    conditions = list(_company_vehicle_conditions(include_demo=include_demo))
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Vehicle.registration_number.ilike(pattern),
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
            )
        )
    if status == "active":
        conditions.append(Vehicle.is_active.is_(True))
    elif status == "inactive":
        conditions.append(Vehicle.is_active.is_(False))
    if nct == "missing":
        conditions.append(Vehicle.nct_expiry_date.is_(None))
    elif nct == "expired":
        conditions.append(Vehicle.nct_expiry_date < today)
    elif nct == "expiring":
        conditions.extend(
            (
                Vehicle.nct_expiry_date >= today,
                Vehicle.nct_expiry_date <= today + timedelta(days=30),
            )
        )
    elif nct == "valid":
        conditions.append(Vehicle.nct_expiry_date > today + timedelta(days=30))

    total = int(
        session.scalar(select(func.count(Vehicle.id)).where(*conditions)) or 0
    )
    order_column = {
        "registration": Vehicle.registration_number,
        "activity": latest_activity,
        "mileage": latest_mileage,
        "nct": Vehicle.nct_expiry_date,
    }[sort_by]
    order_expression = order_column.desc() if sort_order == "desc" else order_column.asc()
    vehicles = session.scalars(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .where(*conditions)
        .order_by(order_expression, Vehicle.registration_number, Vehicle.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    last_values = session.execute(
        select(Vehicle.id, latest_mileage, latest_activity).where(
            Vehicle.id.in_([vehicle.id for vehicle in vehicles])
        )
    ).all()
    details = {
        vehicle_id: (mileage, activity)
        for vehicle_id, mileage, activity in last_values
    }
    return {
        "items": [
            _vehicle_read(
                vehicle,
                *(details.get(vehicle.id, (None, None))),
                today=today,
            )
            for vehicle in vehicles
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_executive_vehicle_detail(
    session: Session, vehicle_id: int, *, include_demo: bool = False
) -> dict[str, Any] | None:
    vehicle = session.scalar(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .where(
            Vehicle.id == vehicle_id,
            *_company_vehicle_conditions(include_demo=include_demo),
        )
    )
    if vehicle is None:
        return None
    today = get_irish_today()
    month_start = today.replace(day=1)
    period = _period_summary(
        session,
        month_start,
        today + timedelta(days=1),
        vehicle_id,
        include_demo=include_demo,
    )
    last_record = session.scalar(
        select(FuelRecord)
        .where(
            FuelRecord.vehicle_id == vehicle.id,
            *_fuel_record_demo_conditions(include_demo),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
    )
    transactions = _transactions_for_vehicle(
        session, vehicle.id, limit=12, include_demo=include_demo
    )
    return {
        **_vehicle_read(
            vehicle,
            last_record.mileage_miles if last_record else None,
            last_record.created_at if last_record else None,
            today=today,
        ),
        "month_diesel_litres": period["litres"],
        "month_cost_eur": period["cost_eur"],
        "month_cost_record_count": period["cost_record_count"],
        "transactions": transactions,
    }


def list_executive_employees(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    include_demo: bool = False,
) -> dict[str, Any]:
    today = get_irish_today()
    month_start_at, tomorrow_at = _date_bounds(
        today.replace(day=1), today + timedelta(days=1)
    )
    conditions = [Employee.role == "employee"]
    if not include_demo:
        conditions.append(Employee.is_demo.is_(False))
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(Employee.name.ilike(pattern), Employee.username.ilike(pattern))
        )

    total = int(
        session.scalar(select(func.count(Employee.id)).where(*conditions)) or 0
    )
    employees = list(
        session.scalars(
            select(Employee)
            .options(selectinload(Employee.vehicles))
            .where(*conditions)
            .order_by(Employee.name.collate("NOCASE"), Employee.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    employee_ids = [employee.id for employee in employees]
    stats_by_employee: dict[int, tuple[Any, ...]] = {}
    if employee_ids:
        in_month = and_(
            FuelRecord.created_at >= month_start_at,
            FuelRecord.created_at < tomorrow_at,
        )
        stats = session.execute(
            select(
                FuelRecord.employee_id,
                func.count(FuelRecord.id),
                func.coalesce(
                    func.sum(
                        case(
                            (FuelRecord.fuel_type == "Diesel", FILL_LITRES),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.count(case((in_month, 1))),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(in_month, FuelRecord.fuel_type == "Diesel"),
                                FILL_LITRES,
                            ),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (and_(in_month, FuelRecord.cost > 0), FuelRecord.cost),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
                func.count(case((and_(in_month, FuelRecord.cost > 0), 1))),
                func.max(FuelRecord.created_at),
            )
            .select_from(FuelRecord)
            .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
            .where(
                FuelRecord.employee_id.in_(employee_ids),
                *_company_vehicle_conditions(include_demo=include_demo),
                *_fuel_record_demo_conditions(include_demo),
            )
            .group_by(FuelRecord.employee_id)
        ).all()
        stats_by_employee = {
            employee_id: (
                int(record_count),
                float(diesel_litres),
                int(month_record_count),
                float(month_diesel_litres),
                float(month_cost_eur),
                int(month_cost_record_count),
                latest_activity_at,
            )
            for (
                employee_id,
                record_count,
                diesel_litres,
                month_record_count,
                month_diesel_litres,
                month_cost_eur,
                month_cost_record_count,
                latest_activity_at,
            ) in stats
        }

    items = []
    for employee in employees:
        (
            record_count,
            diesel_litres,
            month_record_count,
            month_diesel_litres,
            month_cost_eur,
            month_cost_record_count,
            latest_activity_at,
        ) = stats_by_employee.get(
            employee.id, (0, 0.0, 0, 0.0, 0.0, 0, None)
        )
        vehicle_registrations = sorted(
            vehicle.registration_number
            for vehicle in employee.vehicles
            if vehicle.is_company_vehicle
            and (include_demo or not vehicle.is_demo)
        )
        items.append(
            {
                "id": employee.id,
                "name": employee.name,
                "is_active": employee.is_active,
                "vehicle_registrations": vehicle_registrations,
                "record_count": record_count,
                "diesel_litres": diesel_litres,
                "month_record_count": month_record_count,
                "month_diesel_litres": month_diesel_litres,
                "month_cost_eur": month_cost_eur,
                "month_cost_record_count": month_cost_record_count,
                "latest_activity_at": latest_activity_at,
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_executive_employee_records(
    session: Session,
    employee_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    include_demo: bool = False,
) -> dict[str, Any] | None:
    employee_conditions = [
        Employee.id == employee_id,
        Employee.role == "employee",
    ]
    if not include_demo:
        employee_conditions.append(Employee.is_demo.is_(False))
    employee = session.scalar(select(Employee).where(*employee_conditions))
    if employee is None:
        return None

    conditions = [
        FuelRecord.employee_id == employee.id,
        *_company_vehicle_conditions(include_demo=include_demo),
        *_fuel_record_demo_conditions(include_demo),
    ]
    if start_date is not None:
        start_at, _ = _date_bounds(start_date, start_date + timedelta(days=1))
        conditions.append(FuelRecord.created_at >= start_at)
    if end_date is not None:
        _, end_at = _date_bounds(end_date, end_date + timedelta(days=1))
        conditions.append(FuelRecord.created_at < end_at)

    base_query = (
        select(FuelRecord, Vehicle.registration_number)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(*conditions)
    )
    total, diesel_litres, cost_eur, cost_record_count = session.execute(
        select(
            func.count(FuelRecord.id),
            func.coalesce(
                func.sum(
                    case(
                        (FuelRecord.fuel_type == "Diesel", FILL_LITRES),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (FuelRecord.cost > 0, FuelRecord.cost),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
            func.count(case((FuelRecord.cost > 0, 1))),
        )
        .select_from(FuelRecord)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(*conditions)
    ).one()
    records = session.execute(
        base_query
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            _transaction_read(record, registration, employee.name)
            for record, registration in records
        ],
        "total": int(total or 0),
        "diesel_litres": float(diesel_litres or 0.0),
        "cost_eur": float(cost_eur or 0.0),
        "cost_record_count": int(cost_record_count or 0),
        "page": page,
        "page_size": page_size,
    }


def get_my_vehicle(
    session: Session, employee_id: int
) -> dict[str, Any]:
    employee = session.get(Employee, employee_id)
    if employee is None:
        return {"vehicle": None, "available_vehicles": []}
    assigned = session.scalar(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .join(Vehicle.employees)
        .where(
            Employee.id == employee_id,
            Vehicle.is_company_vehicle.is_(False),
            Vehicle.is_active.is_(True),
            Vehicle.is_demo.is_(False),
        )
        .order_by(Vehicle.id)
        .limit(1)
    )
    available = session.scalars(
        select(Vehicle)
        .options(selectinload(Vehicle.employees))
        .where(
            Vehicle.is_company_vehicle.is_(False),
            Vehicle.is_active.is_(True),
            Vehicle.is_demo.is_(False),
            ~Vehicle.employees.any(Employee.id != employee_id),
        )
        .order_by(Vehicle.registration_number)
    ).all()
    detail = (
        _get_personal_vehicle_detail(session, assigned, get_irish_today())
        if assigned is not None
        else None
    )
    return {
        "vehicle": detail,
        "available_vehicles": [
            _vehicle_read(
                vehicle,
                *_latest_vehicle_values(session, vehicle.id),
                today=get_irish_today(),
            )
            for vehicle in available
        ],
    }


def set_my_vehicle(
    session: Session, employee_id: int, vehicle_id: int | None
) -> dict[str, Any]:
    employee = session.scalar(
        select(Employee)
        .options(selectinload(Employee.vehicles))
        .where(Employee.id == employee_id)
    )
    if employee is None:
        raise LookupError("Employee not found.")
    target: Vehicle | None = None
    if vehicle_id is not None:
        target = session.scalar(
            select(Vehicle)
            .options(selectinload(Vehicle.employees))
            .where(
                Vehicle.id == vehicle_id,
                Vehicle.is_company_vehicle.is_(False),
                Vehicle.is_active.is_(True),
                Vehicle.is_demo.is_(False),
            )
        )
        if target is None:
            raise ValueError("Choose an active personal vehicle.")
        if (
            employee not in target.employees
            and any(other.id != employee.id for other in target.employees)
        ):
            raise ValueError("That personal vehicle is already assigned.")

    for vehicle in list(employee.vehicles):
        if not vehicle.is_company_vehicle:
            employee.vehicles.remove(vehicle)
    if target is not None and target not in employee.vehicles:
        employee.vehicles.append(target)
    session.flush()
    return get_my_vehicle(session, employee_id)


def _period_summary(
    session: Session,
    start_date: date,
    end_date: date,
    vehicle_id: int | None = None,
    *,
    company_only: bool = True,
    include_demo: bool = False,
) -> dict[str, Any]:
    start_at, end_at = _date_bounds(start_date, end_date)
    conditions = [
        *_fuel_record_demo_conditions(include_demo),
        FuelRecord.created_at >= start_at,
        FuelRecord.created_at < end_at,
    ]
    if company_only:
        conditions.extend(_company_vehicle_conditions(include_demo=include_demo))
    if vehicle_id is not None:
        conditions.append(FuelRecord.vehicle_id == vehicle_id)
    values = session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (FuelRecord.fuel_type == "Diesel", FILL_LITRES),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
            func.coalesce(
                func.sum(case((FuelRecord.cost > 0, FuelRecord.cost), else_=0.0)),
                0.0,
            ),
            func.count(FuelRecord.id),
            func.count(case((FuelRecord.cost > 0, 1))),
            func.count(case((FuelRecord.cost == 0, 1))),
        )
        .select_from(FuelRecord)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(*conditions)
    ).one()
    return {
        "litres": float(values[0]),
        "cost_eur": float(values[1]),
        "transaction_count": int(values[2]),
        "cost_record_count": int(values[3]),
        "missing_cost_count": int(values[4]),
    }


def _latest_transactions(
    session: Session, limit: int, *, include_demo: bool = False
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(FuelRecord, Vehicle.registration_number, Employee.name)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .outerjoin(Employee, Employee.id == FuelRecord.employee_id)
        .where(
            *_company_vehicle_conditions(include_demo=include_demo),
            *_fuel_record_demo_conditions(include_demo),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(limit)
    ).all()
    return [
        _transaction_read(record, registration, employee_name)
        for record, registration, employee_name in rows
    ]


def _transactions_for_vehicle(
    session: Session,
    vehicle_id: int,
    limit: int,
    *,
    include_demo: bool = False,
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(FuelRecord, Vehicle.registration_number, Employee.name)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .outerjoin(Employee, Employee.id == FuelRecord.employee_id)
        .where(
            Vehicle.id == vehicle_id,
            *_company_vehicle_conditions(include_demo=include_demo),
            *_fuel_record_demo_conditions(include_demo),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(limit)
    ).all()
    return [
        _transaction_read(record, registration, employee_name)
        for record, registration, employee_name in rows
    ]


def _transaction_read(
    record: FuelRecord, registration: str, employee_name: str | None
) -> dict[str, Any]:
    fallback_name = " ".join((record.first_name, record.surname)).strip()
    return {
        "id": record.id,
        "registration_number": registration,
        "employee_name": employee_name or fallback_name or None,
        "fuel_type": record.fuel_type,
        "litres": float(record.current_fill_litres or record.litres),
        "cost_eur": float(record.cost),
        "mileage_miles": record.mileage_miles,
        "current_fill_litres": record.current_fill_litres,
        "cumulative_total_litres": record.cumulative_total_litres,
        "meter_check_status": record.meter_check_status,
        "meter_photo_id": record.meter_photo_id,
        "created_at": record.created_at,
    }


def _vehicle_usage(
    session: Session,
    start_at: datetime,
    end_at: datetime,
    *,
    include_demo: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values = session.execute(
        select(
            Vehicle.id,
            Vehicle.registration_number,
            func.sum(FILL_LITRES),
            func.count(FuelRecord.id),
        )
        .join(FuelRecord, FuelRecord.vehicle_id == Vehicle.id)
        .where(
            *_company_vehicle_conditions(include_demo=include_demo),
            *_fuel_record_demo_conditions(include_demo),
            FuelRecord.fuel_type == "Diesel",
            FuelRecord.created_at >= start_at,
            FuelRecord.created_at < end_at,
        )
        .group_by(Vehicle.id, Vehicle.registration_number)
        .order_by(func.sum(FILL_LITRES).desc(), Vehicle.registration_number)
    ).all()
    mapped = [
        {
            "vehicle_id": row[0],
            "registration_number": row[1],
            "litres": float(row[2] or 0),
            "transaction_count": int(row[3]),
        }
        for row in values
    ]
    return mapped[:5], list(reversed(mapped[-5:])) if len(mapped) > 1 else []


def _global_meter_summary(
    session: Session,
    review_count: int,
    low_confidence_count: int,
    *,
    include_demo: bool = False,
) -> dict[str, Any]:
    state = session.get(GlobalMeterState, 1)
    if state is None:
        return {
            "current_cumulative_total_litres": None,
            "previous_cumulative_total_litres": None,
            "difference_litres": None,
            "last_updated_at": None,
            "last_employee_name": None,
            "last_vehicle_registration": None,
            "latest_current_fill_litres": None,
            "is_demo": False,
            "review_count": review_count,
            "low_confidence_count": low_confidence_count,
        }
    record = (
        session.get(FuelRecord, state.last_transaction_id)
        if state.last_transaction_id is not None
        else None
    )
    if record is not None and record.is_demo and not include_demo:
        current_total = previous_total = difference = None
        last_updated_at = last_employee_name = last_vehicle_registration = None
        latest_current_fill = None
    else:
        employee = (
            session.get(Employee, state.last_employee_id)
            if state.last_employee_id is not None
            else None
        )
        vehicle = (
            session.get(Vehicle, state.last_vehicle_id)
            if state.last_vehicle_id is not None
            else None
        )
        current_total = state.current_cumulative_total_litres
        previous_total = state.previous_cumulative_total_litres
        difference = (
            current_total - previous_total
            if current_total is not None and previous_total is not None
            else None
        )
        last_updated_at = state.last_updated_at
        last_employee_name = employee.name if employee else None
        last_vehicle_registration = vehicle.registration_number if vehicle else None
        latest_current_fill = record.current_fill_litres if record else None
    return {
        "current_cumulative_total_litres": current_total,
        "previous_cumulative_total_litres": previous_total,
        "difference_litres": difference,
        "last_updated_at": last_updated_at,
        "last_employee_name": last_employee_name,
        "last_vehicle_registration": last_vehicle_registration,
        "latest_current_fill_litres": latest_current_fill,
        "is_demo": bool(record.is_demo) if record is not None else False,
        "review_count": review_count,
        "low_confidence_count": low_confidence_count,
    }


def _notifications(
    session: Session,
    nct_alerts: list[dict[str, Any]],
    missing_nct_count: int,
    missing_cost_count: int,
    today: date,
    *,
    include_demo: bool = False,
) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []
    for alert in nct_alerts[:5]:
        days = alert["days_remaining"]
        severity = "urgent" if days is not None and days <= 7 else "warning"
        detail = (
            "NCT expired."
            if days is not None and days < 0
            else "NCT expires today."
            if days == 0
            else f"NCT expires in {days} days."
        )
        notifications.append(
            {
                "id": f"nct-{alert['vehicle_id']}-{alert['nct_expiry_date']}",
                "kind": "nct",
                "severity": severity,
                "title": f"NCT: {alert['registration_number']}",
                "description": detail,
                "vehicle_id": alert["vehicle_id"],
                "registration_number": alert["registration_number"],
                "created_at": None,
            }
        )
    if missing_nct_count:
        notifications.append(
            {
                "id": f"nct-missing-{today.isoformat()}",
                "kind": "nct",
                "severity": "info",
                "title": "NCT dates need attention",
                "description": f"{missing_nct_count} company vehicle(s) have no NCT date recorded.",
                "vehicle_id": None,
                "registration_number": None,
                "created_at": None,
            }
        )
    discrepancies = session.execute(
        select(FuelRecord.id, Vehicle.id, Vehicle.registration_number, FuelRecord.created_at)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(
            *_company_vehicle_conditions(include_demo=include_demo),
            *_fuel_record_demo_conditions(include_demo),
            FuelRecord.meter_check_status == "discrepancy",
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(3)
    ).all()
    for record_id, vehicle_id, registration, created_at in discrepancies:
        notifications.append(
            {
                "id": f"meter-review-{record_id}",
                "kind": "meter_review",
                "severity": "warning",
                "title": f"Reading needs review: {registration}",
                "description": "A cumulative meter discrepancy was recorded.",
                "vehicle_id": vehicle_id,
                "registration_number": registration,
                "created_at": created_at,
            }
        )
    if missing_cost_count:
        notifications.append(
            {
                "id": f"cost-data-{today.strftime('%Y-%m')}",
                "kind": "cost_data",
                "severity": "info",
                "title": "Fuel costs are incomplete",
                "description": (
                    f"{missing_cost_count} fuel record(s) this month have "
                    "no recorded cost."
                ),
                "vehicle_id": None,
                "registration_number": None,
                "created_at": None,
            }
        )
    return notifications


def _vehicle_read(
    vehicle: Vehicle,
    latest_mileage_miles: float | None,
    latest_activity_at: datetime | None,
    *,
    today: date,
) -> dict[str, Any]:
    status, days_remaining = _nct_status(vehicle.nct_expiry_date, today)
    if status == "no_alert":
        status = "valid"
    return {
        "id": vehicle.id,
        "registration_number": vehicle.registration_number,
        "make": vehicle.make,
        "model": vehicle.model,
        "fuel_type": vehicle.fuel_type,
        "tank_capacity": vehicle.tank_capacity,
        "is_active": vehicle.is_active,
        "is_company_vehicle": vehicle.is_company_vehicle,
        "employee_names": sorted(employee.name for employee in vehicle.employees),
        "nct_expiry_date": vehicle.nct_expiry_date,
        "nct_status": status,
        "nct_days_remaining": days_remaining,
        "latest_mileage_miles": latest_mileage_miles,
        "latest_activity_at": latest_activity_at,
    }


def _latest_vehicle_values(
    session: Session, vehicle_id: int
) -> tuple[float | None, datetime | None]:
    record = session.scalar(
        select(FuelRecord)
        .where(FuelRecord.vehicle_id == vehicle_id, FuelRecord.is_demo.is_(False))
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(1)
    )
    return (
        (record.mileage_miles, record.created_at)
        if record is not None
        else (None, None)
    )


def _get_personal_vehicle_detail(
    session: Session, vehicle: Vehicle, today: date
) -> dict[str, Any]:
    latest_mileage, latest_activity = _latest_vehicle_values(session, vehicle.id)
    month_summary = _period_summary(
        session,
        today.replace(day=1),
        today + timedelta(days=1),
        vehicle.id,
        company_only=False,
    )
    rows = session.execute(
        select(FuelRecord, Vehicle.registration_number, Employee.name)
        .join(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .outerjoin(Employee, Employee.id == FuelRecord.employee_id)
        .where(
            Vehicle.id == vehicle.id,
            FuelRecord.is_demo.is_(False),
        )
        .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        .limit(12)
    ).all()
    return {
        **_vehicle_read(vehicle, latest_mileage, latest_activity, today=today),
        "month_diesel_litres": month_summary["litres"],
        "month_cost_eur": month_summary["cost_eur"],
        "month_cost_record_count": month_summary["cost_record_count"],
        "transactions": [
            _transaction_read(record, registration, employee_name)
            for record, registration, employee_name in rows
        ],
    }


def _date_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(start_date, time.min, tzinfo=IRELAND_TIME_ZONE)
    end = datetime.combine(end_date, time.min, tzinfo=IRELAND_TIME_ZONE)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _vehicle_demo_conditions(include_demo: bool) -> tuple[Any, ...]:
    return () if include_demo else (Vehicle.is_demo.is_(False),)


def _fuel_record_demo_conditions(include_demo: bool) -> tuple[Any, ...]:
    return () if include_demo else (FuelRecord.is_demo.is_(False),)


def _company_vehicle_conditions(
    *, include_demo: bool = False
) -> tuple[Any, ...]:
    return (
        Vehicle.is_company_vehicle.is_(True),
        *_vehicle_demo_conditions(include_demo),
    )
