from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_current_employee
from backend.app.models import Employee
from backend.app.schemas.dashboard import DashboardStatus
from backend.app.services.dashboard import get_dashboard_status


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStatus)
def read_dashboard(
    _: Annotated[Employee, Depends(get_current_employee)],
) -> DashboardStatus:
    return get_dashboard_status()
