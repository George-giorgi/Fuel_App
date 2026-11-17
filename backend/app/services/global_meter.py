from datetime import datetime, timezone
from decimal import Decimal
import math

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterEvent,
    GlobalMeterState,
    MeterPhoto,
    Vehicle,
)
from backend.app.services.meter_readings import (
    decimal_to_milli_litres,
    milli_litres_to_decimal,
)
from backend.app.services.photo_storage import read_photo


class GlobalMeterConcurrentUpdate(ValueError):
    pass


def get_or_create_global_meter_state(session: Session) -> GlobalMeterState:
    state = session.get(GlobalMeterState, 1)
    if state is not None:
        return state

    records = list(
        session.scalars(
            select(FuelRecord)
            .where(
                FuelRecord.cumulative_total_litres.is_not(None),
                FuelRecord.cumulative_total_litres >= 0,
            )
            .order_by(FuelRecord.created_at.desc(), FuelRecord.id.desc())
        ).all()
    )
    records = [
        record
        for record in records
        if math.isfinite(float(record.cumulative_total_litres))
    ]
    if len({record.created_at for record in records}) <= 1:
        records.sort(
            key=lambda record: (record.cumulative_total_litres, record.id),
            reverse=True,
        )

    latest = records[0] if records else None
    previous = records[1] if len(records) > 1 else None
    state = GlobalMeterState(
        id=1,
        current_cumulative_total_litres=(
            latest.cumulative_total_litres if latest is not None else None
        ),
        current_total_integer=(
            latest.cumulative_total_integer if latest is not None else None
        ),
        current_total_raw_digits=(
            latest.cumulative_total_raw_digits if latest is not None else None
        ),
        previous_cumulative_total_litres=(
            previous.cumulative_total_litres if previous is not None else None
        ),
        previous_total_integer=(
            previous.cumulative_total_integer if previous is not None else None
        ),
        last_updated_at=latest.created_at if latest is not None else None,
        last_transaction_id=latest.id if latest is not None else None,
        last_employee_id=latest.employee_id if latest is not None else None,
        last_vehicle_id=latest.vehicle_id if latest is not None else None,
        revision=0,
    )
    session.add(state)
    session.flush()
    return state


def update_global_meter_after_fill(
    session: Session,
    state: GlobalMeterState,
    record: FuelRecord,
    employee: Employee,
    vehicle: Vehicle,
    updated_at: datetime,
) -> None:
    expected_revision = state.revision
    result = session.execute(
        update(GlobalMeterState)
        .where(
            GlobalMeterState.id == 1,
            GlobalMeterState.revision == expected_revision,
        )
        .values(
            previous_cumulative_total_litres=state.current_cumulative_total_litres,
            current_cumulative_total_litres=record.cumulative_total_litres,
            previous_total_integer=record.previous_global_total_integer,
            current_total_integer=record.cumulative_total_integer,
            current_total_raw_digits=record.cumulative_total_raw_digits,
            last_updated_at=updated_at,
            last_transaction_id=record.id,
            last_employee_id=employee.id,
            last_vehicle_id=vehicle.id,
            last_event_id=None,
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise GlobalMeterConcurrentUpdate(
            "The global meter changed while this fill was being saved. "
            "Review the latest reading and submit again."
        )

    state.previous_cumulative_total_litres = state.current_cumulative_total_litres
    state.current_cumulative_total_litres = record.cumulative_total_litres
    state.previous_total_integer = record.previous_global_total_integer
    state.current_total_integer = record.cumulative_total_integer
    state.current_total_raw_digits = record.cumulative_total_raw_digits
    state.last_updated_at = updated_at
    state.last_transaction_id = record.id
    state.last_employee_id = employee.id
    state.last_vehicle_id = vehicle.id
    state.last_event_id = None
    state.revision = expected_revision + 1


def advance_global_meter_revision(
    session: Session, state: GlobalMeterState
) -> None:
    expected_revision = state.revision
    result = session.execute(
        update(GlobalMeterState)
        .where(
            GlobalMeterState.id == 1,
            GlobalMeterState.revision == expected_revision,
        )
        .values(revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise GlobalMeterConcurrentUpdate(
            "The global meter changed while this fill was being saved. "
            "Review the latest reading and submit again."
        )
    state.revision = expected_revision + 1


def create_global_meter_event(
    session: Session,
    employee: Employee,
    event_type: str,
    baseline_total: int | float | Decimal,
    notes: str,
) -> GlobalMeterEvent:
    try:
        baseline_total_integer = decimal_to_milli_litres(
            Decimal(str(baseline_total))
        )
    except (ValueError, ArithmeticError) as error:
        raise ValueError(
            "Global meter event baseline must be non-negative with no more than 3 decimals."
        ) from error
    state = get_or_create_global_meter_state(session)
    if event_type == "baseline" and state.current_cumulative_total_litres is not None:
        raise ValueError("A baseline can only be established before the first reading.")
    if event_type != "baseline" and state.current_cumulative_total_litres is None:
        raise ValueError("Establish the initial global meter baseline first.")
    now = datetime.now(timezone.utc)
    baseline_total_compat = float(
        milli_litres_to_decimal(baseline_total_integer)
    )
    event = GlobalMeterEvent(
        event_type=event_type,
        previous_cumulative_total_litres=state.current_cumulative_total_litres,
        baseline_cumulative_total_litres=baseline_total_compat,
        authorized_by_employee_id=employee.id,
        occurred_at=now,
        notes=notes,
        previous_total_integer=(
            state.current_total_integer
            if state.current_total_integer is not None
            else None
        ),
        baseline_total_integer=baseline_total_integer,
        previous_total_raw_digits=state.current_total_raw_digits,
        baseline_total_raw_digits=str(baseline_total_integer),
    )
    session.add(event)
    session.flush()

    expected_revision = state.revision
    result = session.execute(
        update(GlobalMeterState)
        .where(
            GlobalMeterState.id == 1,
            GlobalMeterState.revision == expected_revision,
        )
        .values(
            previous_cumulative_total_litres=state.current_cumulative_total_litres,
            current_cumulative_total_litres=baseline_total_compat,
            previous_total_integer=(
                state.current_total_integer
                if state.current_total_integer is not None
                else None
            ),
            current_total_integer=baseline_total_integer,
            current_total_raw_digits=str(baseline_total_integer),
            last_updated_at=now,
            last_transaction_id=None,
            last_employee_id=employee.id,
            last_vehicle_id=None,
            last_event_id=event.id,
            revision=expected_revision + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise GlobalMeterConcurrentUpdate(
            "The global meter changed while this event was being saved. "
            "Review the latest reading and record the event again."
        )

    state.previous_cumulative_total_litres = state.current_cumulative_total_litres
    state.current_cumulative_total_litres = baseline_total_compat
    state.previous_total_integer = (
        state.current_total_integer
        if state.current_total_integer is not None
        else None
    )
    state.current_total_integer = baseline_total_integer
    state.current_total_raw_digits = str(baseline_total_integer)
    state.last_updated_at = now
    state.last_transaction_id = None
    state.last_employee_id = employee.id
    state.last_vehicle_id = None
    state.last_event_id = event.id
    state.revision = expected_revision + 1
    return event


def get_global_meter_summary(session: Session) -> dict[str, object]:
    state = get_or_create_global_meter_state(session)
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
    record = (
        session.get(FuelRecord, state.last_transaction_id)
        if state.last_transaction_id is not None
        else None
    )
    event = (
        session.get(GlobalMeterEvent, state.last_event_id)
        if state.last_event_id is not None
        else None
    )
    photo_id = record.meter_photo_id if record is not None else None
    return {
        "current_cumulative_total_litres": (
            state.current_cumulative_total_litres
        ),
        "current_total_integer": state.current_total_integer,
        "previous_total_integer": state.previous_total_integer,
        "current_total_raw_digits": state.current_total_raw_digits,
        "previous_cumulative_total_litres": (
            state.previous_cumulative_total_litres
        ),
        "difference_litres": (
            state.current_cumulative_total_litres
            - state.previous_cumulative_total_litres
            if state.current_cumulative_total_litres is not None
            and state.previous_cumulative_total_litres is not None
            else None
        ),
        "difference_integer": (
            state.current_total_integer - state.previous_total_integer
            if state.current_total_integer is not None
            and state.previous_total_integer is not None
            else None
        ),
        "last_updated_at": state.last_updated_at,
        "last_transaction_id": state.last_transaction_id,
        "last_employee_name": employee.name if employee is not None else None,
        "last_vehicle_registration": (
            vehicle.registration_number if vehicle is not None else None
        ),
        "last_meter_photo_id": photo_id,
        "last_meter_photo_url": (
            f"/api/management/global-meter/transactions/{state.last_transaction_id}/photo"
            if photo_id is not None and state.last_transaction_id is not None
            else None
        ),
        "last_update_source": (
            "fill" if record is not None else event.event_type if event else None
        ),
    }


def list_global_meter_history(
    session: Session, limit: int = 100
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    records = session.execute(
        select(FuelRecord, Employee.name, Vehicle.registration_number)
        .outerjoin(Employee, Employee.id == FuelRecord.employee_id)
        .outerjoin(Vehicle, Vehicle.id == FuelRecord.vehicle_id)
        .where(
            FuelRecord.cumulative_total_litres.is_not(None),
            FuelRecord.cumulative_total_litres >= 0,
        )
        .order_by(FuelRecord.created_at.asc(), FuelRecord.id.asc())
    ).all()
    for record, employee_name, registration_number in records:
        if not math.isfinite(float(record.cumulative_total_litres)):
            continue
        entries.append(
            {
                "_timestamp": record.created_at,
                "_sort_order": 0,
                "_id": record.id,
                "id": f"fill-{record.id}",
                "kind": "fill",
                "created_at": record.created_at,
                "previous_cumulative_total_litres": None,
                "current_fill_litres": record.current_fill_litres,
                "cumulative_total_litres": record.cumulative_total_litres,
                "current_fill_milli_litres": record.current_fill_milli_litres,
                "top_current_fill_milli_litres": (
                    record.top_current_fill_milli_litres
                ),
                "cumulative_total_integer": record.cumulative_total_integer,
                "previous_total_integer": record.previous_global_total_integer,
                "reading_source": record.reading_source,
                "fill_source": record.meter_reading_source,
                "warnings": record.meter_warnings,
                "difference_integer": (
                    record.cumulative_total_integer
                    - record.previous_global_total_integer
                    if record.cumulative_total_integer is not None
                    and record.previous_global_total_integer is not None
                    else None
                ),
                "difference_litres": (
                    float(
                        milli_litres_to_decimal(
                            record.cumulative_total_integer
                            - record.previous_global_total_integer
                        )
                    )
                    if record.cumulative_total_integer is not None
                    and record.previous_global_total_integer is not None
                    else None
                ),
                "employee_name": employee_name,
                "vehicle_registration": registration_number,
                "meter_photo_id": record.meter_photo_id,
                "meter_photo_url": (
                    f"/api/management/global-meter/transactions/{record.id}/photo"
                    if record.meter_photo_id is not None
                    else None
                ),
                "status": record.meter_check_status,
                "is_demo": record.is_demo,
                "notes": (
                    record.demo_key
                    if record.demo_key
                    and record.demo_key.startswith("global-meter-test:")
                    else None
                ),
            }
        )

    events = session.execute(
        select(GlobalMeterEvent, Employee.name)
        .join(Employee, Employee.id == GlobalMeterEvent.authorized_by_employee_id)
        .order_by(GlobalMeterEvent.occurred_at.asc(), GlobalMeterEvent.id.asc())
    ).all()
    for event, employee_name in events:
        entries.append(
            {
                "_timestamp": event.occurred_at,
                "_sort_order": 1,
                "_id": event.id,
                "id": f"event-{event.id}",
                "kind": event.event_type,
                "created_at": event.occurred_at,
                "previous_cumulative_total_litres": (
                    event.previous_cumulative_total_litres
                ),
                "current_fill_litres": None,
                "cumulative_total_litres": (
                    event.baseline_cumulative_total_litres
                ),
                "current_fill_milli_litres": None,
                "top_current_fill_milli_litres": None,
                "cumulative_total_integer": event.baseline_total_integer,
                "previous_total_integer": event.previous_total_integer,
                "reading_source": "MANUAL" if event.event_type == "baseline" else None,
                "fill_source": None,
                "warnings": None,
                "difference_integer": (
                    event.baseline_total_integer - event.previous_total_integer
                    if event.baseline_total_integer is not None
                    and event.previous_total_integer is not None
                    else None
                ),
                "difference_litres": (
                    float(
                        milli_litres_to_decimal(
                            event.baseline_total_integer
                            - event.previous_total_integer
                        )
                    )
                    if event.baseline_total_integer is not None
                    and event.previous_total_integer is not None
                    else None
                ),
                "employee_name": employee_name,
                "vehicle_registration": None,
                "meter_photo_id": None,
                "meter_photo_url": None,
                "status": event.event_type,
                "is_demo": False,
                "notes": event.notes,
            }
        )

    entries.sort(
        key=lambda entry: (
            _timestamp_sort_value(entry["_timestamp"]),
            entry["_sort_order"],
            entry["_id"],
        )
    )
    previous_total: float | None = None
    for entry in entries:
        if entry["kind"] == "fill":
            entry["previous_cumulative_total_litres"] = previous_total
            entry["difference_litres"] = (
                entry["cumulative_total_litres"] - previous_total
                if previous_total is not None
                else None
            )
        else:
            previous_total = entry["previous_cumulative_total_litres"]
        previous_total = entry["cumulative_total_litres"]

    return [
        {key: value for key, value in entry.items() if not key.startswith("_")}
        for entry in reversed(entries[-limit:])
    ]


def get_global_meter_photo(
    session: Session, transaction_id: int
) -> tuple[bytes, str] | None:
    record = session.get(FuelRecord, transaction_id)
    if record is None or record.meter_photo_id is None:
        return None
    photo = session.get(MeterPhoto, record.meter_photo_id)
    if photo is None:
        return None

    content = read_photo(photo.storage_key)
    if content is None:
        return None
    return content, photo.content_type


def _timestamp_sort_value(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
