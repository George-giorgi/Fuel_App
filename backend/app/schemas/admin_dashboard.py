from datetime import date, datetime

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


class AdminRecentFuelRecordRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    id: int
    employee_name: str
    reg_number: str
    created_at: datetime
    current_fill_litres: float
    current_fill_milli_litres: int | None
    mileage_miles: float
    meter_reading_source: str
    reading_source: str | None
    cumulative_total_integer: int | None
    previous_global_total_integer: int | None
    top_current_fill_milli_litres: int | None
    meter_check_status: str
    meter_warnings: list[str] | None


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
    recent_records: list[AdminRecentFuelRecordRead]
