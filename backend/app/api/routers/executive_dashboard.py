from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_management
from backend.app.db.session import get_db_session
from backend.app.models import Employee
from backend.app.schemas.executive_dashboard import (
    ExecutiveAnalyticsRead,
    ExecutiveEmployeeListRead,
    ExecutiveEmployeeRecordsRead,
    ExecutiveOverviewRead,
    ExecutiveVehicleDetailRead,
    ExecutiveVehicleListRead,
    MyVehicleRead,
    SetMyVehicleRequest,
)
from backend.app.services.executive_dashboard import (
    get_executive_analytics,
    get_executive_overview,
    get_executive_vehicle_detail,
    get_my_vehicle,
    list_executive_employee_records,
    list_executive_employees,
    list_executive_vehicles,
    set_my_vehicle,
)


router = APIRouter(prefix="/api/executive", tags=["executive dashboard"])


@router.get("/dashboard", response_model=ExecutiveOverviewRead)
def executive_overview(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> ExecutiveOverviewRead:
    return ExecutiveOverviewRead.model_validate(
        get_executive_overview(session, include_demo=True)
    )


@router.get("/analytics", response_model=ExecutiveAnalyticsRead)
def executive_analytics(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
    range_days: Annotated[
        int, Query(description="Supported values: 7, 30, or 90.")
    ] = 30,
) -> ExecutiveAnalyticsRead:
    if range_days not in {7, 30, 90}:
        raise HTTPException(
            status_code=422,
            detail="range_days must be 7, 30, or 90.",
        )
    return ExecutiveAnalyticsRead.model_validate(
        get_executive_analytics(
            session, range_days, include_demo=True
        )
    )


@router.get("/vehicles", response_model=ExecutiveVehicleListRead)
def executive_vehicles(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[Literal["all", "active", "inactive"], Query()] = "all",
    nct: Annotated[
        Literal["all", "valid", "expiring", "expired", "missing"], Query()
    ] = "all",
    sort_by: Annotated[
        Literal["registration", "activity", "mileage", "nct"], Query()
    ] = "registration",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> ExecutiveVehicleListRead:
    result = list_executive_vehicles(
        session,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        nct=nct,
        sort_by=sort_by,
        sort_order=sort_order,
        include_demo=True,
    )
    return ExecutiveVehicleListRead.model_validate(result)


@router.get("/employees", response_model=ExecutiveEmployeeListRead)
def executive_employees(
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> ExecutiveEmployeeListRead:
    result = list_executive_employees(
        session,
        page=page,
        page_size=page_size,
        search=search,
        include_demo=True,
    )
    return ExecutiveEmployeeListRead.model_validate(result)


@router.get(
    "/employees/{employee_id}/fuel-records",
    response_model=ExecutiveEmployeeRecordsRead,
)
def executive_employee_fuel_records(
    employee_id: Annotated[int, Path(ge=1)],
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> ExecutiveEmployeeRecordsRead:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="Start date must be on or before end date.",
        )
    result = list_executive_employee_records(
        session,
        employee_id,
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        include_demo=True,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return ExecutiveEmployeeRecordsRead.model_validate(result)


@router.get("/vehicles/{vehicle_id}", response_model=ExecutiveVehicleDetailRead)
def executive_vehicle_detail(
    vehicle_id: Annotated[int, Path(ge=1)],
    session: Annotated[Session, Depends(get_db_session)],
    _: Annotated[Employee, Depends(require_management)],
) -> ExecutiveVehicleDetailRead:
    detail = get_executive_vehicle_detail(
        session, vehicle_id, include_demo=True
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Company vehicle not found.")
    return ExecutiveVehicleDetailRead.model_validate(detail)


@router.get("/my-vehicle", response_model=MyVehicleRead)
def my_personal_vehicle(
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(require_management)],
) -> MyVehicleRead:
    return MyVehicleRead.model_validate(get_my_vehicle(session, employee.id))


@router.put("/my-vehicle", response_model=MyVehicleRead)
def set_personal_vehicle(
    request: SetMyVehicleRequest,
    session: Annotated[Session, Depends(get_db_session)],
    employee: Annotated[Employee, Depends(require_management)],
) -> MyVehicleRead:
    try:
        result = set_my_vehicle(session, employee.id, request.vehicle_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return MyVehicleRead.model_validate(result)
