from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_current_employee
from backend.app.models import Employee
from backend.app.schemas.inventory import InventoryStatus
from backend.app.services.inventory import get_inventory_status


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("", response_model=InventoryStatus)
def read_inventory(
    _: Annotated[Employee, Depends(get_current_employee)],
) -> InventoryStatus:
    return get_inventory_status()
