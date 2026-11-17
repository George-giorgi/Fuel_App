from datetime import date
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_admin, require_management
from backend.app.db.session import get_db_session
from backend.app.models import Employee, FuelRecord, MeterPhoto, Vehicle
from backend.app.repositories.fuel_records import get_latest_vehicle_odometer
from backend.app.repositories.vehicles import get_vehicle_by_id
from backend.app.schemas import FuelRecordRead
from backend.app.schemas.admin_dashboard import (
    AdminEmployeeRead,
    AdminFuelSummaryRead,
    AdminOperationalDataClearRead,
    AdminOperationalDataClearRequest,
)
from backend.app.schemas.employee import (
    AdminEmployeeCreatedRead,
    EmployeeCreate,
    EmployeeRoleUpdate,
    EmployeeStatusUpdate,
)
from backend.app.schemas.nct import NctAlertsRead, VehicleNctRead, VehicleNctUpdate
from backend.app.schemas.odometer_correction import (
    OdometerCorrectionCreate,
    OdometerCorrectionRead,
)
from backend.app.schemas.vehicle import VehicleCreate, VehicleQrRead, VehicleRead
from backend.app.services.auth import create_employee
from backend.app.services.application_reset import clear_operational_data
from backend.app.services.admin_dashboard import (
    AdminEmployeeNotFound,
    InvalidAdminDateRange,
    get_admin_fuel_summary,
    list_admin_employees,
    list_employee_fuel_records,
    update_employee_role,
    update_employee_status,
)
from backend.app.services.vehicles import (
    create_vehicle,
    get_registered_vehicles,
    issue_vehicle_qr,
)
from backend.app.services.vehicle_meter_events import authorize_odometer_correction
from backend.app.services.nct import (
    get_nct_alerts,
    get_vehicle_nct,
    list_vehicle_nct,
    update_vehicle_nct,
)
from backend.app.services.photo_storage import PhotoStorageError, delete_photos


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["administration"])


@router.get("/nct-alerts", response_model=NctAlertsRead)
def nct_expiry_alerts(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> NctAlertsRead:
    return NctAlertsRead.model_validate(get_nct_alerts(session))


@router.get("/vehicles/nct", response_model=list[VehicleNctRead])
def registered_vehicle_nct(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> list[VehicleNctRead]:
    return [
        VehicleNctRead.model_validate(vehicle)
        for vehicle in list_vehicle_nct(session)
    ]


@router.patch(
    "/vehicles/{vehicle_id}/nct",
    response_model=VehicleNctRead,
)
def set_vehicle_nct_expiry(
    vehicle_id: Annotated[int, Path(ge=1)],
    request: VehicleNctUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> VehicleNctRead:
    vehicle = update_vehicle_nct(session, vehicle_id, request.nct_expiry_date)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    updated = get_vehicle_nct(session, vehicle_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return VehicleNctRead.model_validate(updated)


@router.get("/employees", response_model=list[AdminEmployeeRead])
def registered_employees(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> list[Employee]:
    return list_admin_employees(session)


@router.get(
    "/employees/{employee_id}/fuel-records",
    response_model=list[FuelRecordRead],
)
def employee_fuel_records(
    employee_id: int,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> list[FuelRecord]:
    try:
        return list_employee_fuel_records(
            session, employee_id, start_date, end_date
        )
    except AdminEmployeeNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except InvalidAdminDateRange as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/fuel-summary", response_model=AdminFuelSummaryRead)
def admin_fuel_summary(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> AdminFuelSummaryRead:
    try:
        summary = get_admin_fuel_summary(session, start_date, end_date)
    except InvalidAdminDateRange as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AdminFuelSummaryRead.model_validate(summary)


@router.post(
    "/operational-data/clear",
    response_model=AdminOperationalDataClearRead,
)
def clear_admin_operational_data(
    request: AdminOperationalDataClearRequest,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> AdminOperationalDataClearRead:
    photo_keys = list(
        session.scalars(select(MeterPhoto.storage_key)).all()
    )
    try:
        delete_photos(photo_keys)
    except PhotoStorageError as error:
        logger.exception("Could not remove meter photos during data cleanup.")
        raise HTTPException(
            status_code=503,
            detail="Could not delete all stored meter photos. No database records were cleared; retry the cleanup.",
        ) from error
    clear_operational_data(session)

    return AdminOperationalDataClearRead(
        message="Operational records cleared. All users and vehicles were retained.",
        deleted_meter_photos=len(photo_keys),
        retained_users=session.scalar(select(func.count()).select_from(Employee)) or 0,
        retained_vehicles=session.scalar(select(func.count()).select_from(Vehicle)) or 0,
    )


@router.post(
    "/employees", response_model=AdminEmployeeCreatedRead, status_code=201
)
def add_employee(
    request: EmployeeCreate,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> AdminEmployeeCreatedRead:
    vehicle_to_assign = None
    if request.vehicle_id is not None:
        vehicle_to_assign = get_vehicle_by_id(session, request.vehicle_id)
        if vehicle_to_assign is None:
            raise HTTPException(status_code=404, detail="Active vehicle not found.")

    try:
        employee = create_employee(
            session,
            str(request.email),
            request.name,
            request.password.get_secret_value(),
            request.role,
        )
    except IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="An employee with that email already exists."
        ) from error
    if vehicle_to_assign is None and request.vehicle_registration_number is not None:
        try:
            vehicle_to_assign = create_vehicle(
                session,
                request.vehicle_registration_number,
                make=request.vehicle_make,
                model=request.vehicle_model,
                fuel_type=request.vehicle_fuel_type,
                tank_capacity=request.vehicle_tank_capacity,
                nct_expiry_date=request.nct_expiry_date,
                is_company_vehicle=request.vehicle_is_company_vehicle,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=409, detail="That vehicle is already registered."
            ) from error
    if vehicle_to_assign is not None:
        employee.vehicles.append(vehicle_to_assign)

    return AdminEmployeeCreatedRead.model_validate(employee).model_copy(
        update={
            "assigned_vehicle": (
                VehicleRead.model_validate(vehicle_to_assign)
                if vehicle_to_assign is not None
                else None
            )
        }
    )


@router.patch(
    "/employees/{employee_id}/role",
    response_model=AdminEmployeeRead,
)
def change_employee_role(
    employee_id: Annotated[int, Path(ge=1)],
    request: EmployeeRoleUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> AdminEmployeeRead:
    employee = update_employee_role(session, employee_id, request.role)
    if employee is None:
        raise HTTPException(
            status_code=404, detail="Non-administrator account not found."
        )
    return AdminEmployeeRead.model_validate(employee)


@router.patch(
    "/employees/{employee_id}/status",
    response_model=AdminEmployeeRead,
)
def change_employee_status(
    employee_id: Annotated[int, Path(ge=1)],
    request: EmployeeStatusUpdate,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> AdminEmployeeRead:
    employee = update_employee_status(
        session, employee_id, request.is_active
    )
    if employee is None:
        raise HTTPException(
            status_code=404, detail="Non-administrator account not found."
        )
    return AdminEmployeeRead.model_validate(employee)


@router.post("/vehicles", response_model=VehicleRead, status_code=201)
def add_vehicle(
    request: VehicleCreate,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> VehicleRead:
    try:
        vehicle = create_vehicle(
            session,
            request.registration_number,
            make=request.make,
            model=request.model,
            fuel_type=request.fuel_type,
            tank_capacity=request.tank_capacity,
            nct_expiry_date=request.nct_expiry_date,
            is_company_vehicle=request.is_company_vehicle,
        )
        return VehicleRead.model_validate(vehicle)
    except IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="That vehicle is already registered."
        ) from error


@router.get("/vehicles", response_model=list[VehicleRead])
def registered_vehicles(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> list[VehicleRead]:
    vehicles = []
    for vehicle in get_registered_vehicles(session):
        vehicle_read = VehicleRead.model_validate(vehicle)
        vehicles.append(
            vehicle_read.model_copy(
                update={
                    "last_recorded_odometer_miles": get_latest_vehicle_odometer(
                        session, vehicle.id
                    )
                }
            )
        )
    return vehicles


@router.post(
    "/vehicles/{vehicle_id}/qr-code",
    response_model=VehicleQrRead,
)
def generate_vehicle_qr(
    vehicle_id: int,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_admin)],
) -> VehicleQrRead:
    provisioned = issue_vehicle_qr(session, vehicle_id)
    if provisioned is None:
        raise HTTPException(status_code=404, detail="Active vehicle not found.")
    vehicle, qr_payload = provisioned
    response.headers["Cache-Control"] = "no-store"
    return VehicleQrRead(
        registration_number=vehicle.registration_number,
        qr_payload=qr_payload,
    )


@router.post(
    "/vehicles/{vehicle_id}/odometer-corrections",
    response_model=OdometerCorrectionRead,
    status_code=201,
)
def authorize_vehicle_odometer_correction(
    vehicle_id: int,
    request: OdometerCorrectionCreate,
    session: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[Employee, Depends(require_admin)],
) -> OdometerCorrectionRead:
    vehicle = get_vehicle_by_id(session, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    try:
        correction = authorize_odometer_correction(
            session,
            vehicle,
            admin,
            request.authorized_odometer_miles,
            request.notes,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return OdometerCorrectionRead.model_validate(correction)
