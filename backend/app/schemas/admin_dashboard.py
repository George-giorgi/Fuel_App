from datetime import date

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.auth import EmployeeRead
from backend.app.schemas.fuel_record import to_camel_case


class AdminEmployeeRead(EmployeeRead):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    is_active: bool


class AdminTopVehicleRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    vehicle_id: int | None
    registration_number: str
    total_fill_litres: float
    fill_count: int


class AdminFuelSummaryRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    available_from: date | None
    available_to: date | None
    start_date: date | None
    end_date: date | None
    fill_count: int
    total_fill_litres: float
    total_cost: float
    cost_record_count: int
    top_vehicles: list[AdminTopVehicleRead]
