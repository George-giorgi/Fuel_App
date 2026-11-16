from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.fuel_record import to_camel_case


class ExecutiveBaseRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)


class ExecutiveVehicleRead(ExecutiveBaseRead):
    id: int
    registration_number: str
    make: str | None
    model: str | None
    fuel_type: str | None
    tank_capacity: float | None
    is_active: bool
    is_company_vehicle: bool
    employee_names: list[str]
    nct_expiry_date: date | None
    nct_status: str
    nct_days_remaining: int | None
    latest_mileage_miles: float | None
    latest_activity_at: datetime | None


class ExecutiveTransactionRead(ExecutiveBaseRead):
    id: int
    registration_number: str
    employee_name: str | None
    fuel_type: str
    litres: float
    cost_eur: float
    mileage_miles: float
    current_fill_litres: float | None
    cumulative_total_litres: float | None
    meter_check_status: str
    meter_photo_id: int | None
    created_at: datetime


class ExecutiveNctAlertRead(ExecutiveBaseRead):
    vehicle_id: int
    registration_number: str
    employee_names: list[str]
    nct_expiry_date: date | None
    days_remaining: int | None
    status: str


class ExecutiveNotificationRead(ExecutiveBaseRead):
    id: str
    kind: Literal["nct", "meter_review", "cost_data"]
    severity: Literal["urgent", "warning", "info"]
    title: str
    description: str
    vehicle_id: int | None = None
    registration_number: str | None = None
    created_at: datetime | None = None


class ExecutivePeriodSummaryRead(ExecutiveBaseRead):
    litres: float
    cost_eur: float
    transaction_count: int
    cost_record_count: int
    missing_cost_count: int


class ExecutiveMeterRead(ExecutiveBaseRead):
    current_cumulative_total_litres: float | None
    previous_cumulative_total_litres: float | None
    difference_litres: float | None
    last_updated_at: datetime | None
    last_employee_name: str | None
    last_vehicle_registration: str | None
    latest_current_fill_litres: float | None
    is_demo: bool
    review_count: int
    low_confidence_count: int


class ExecutiveFleetRead(ExecutiveBaseRead):
    total_vehicles: int
    active_vehicles: int
    inactive_vehicles: int


class ExecutiveNctSummaryRead(ExecutiveBaseRead):
    valid_count: int
    expiring_count: int
    expired_count: int
    missing_date_count: int
    alerts: list[ExecutiveNctAlertRead]


class ExecutiveOverviewRead(ExecutiveBaseRead):
    today: date
    fleet: ExecutiveFleetRead
    today_summary: ExecutivePeriodSummaryRead
    month_summary: ExecutivePeriodSummaryRead
    meter: ExecutiveMeterRead
    nct: ExecutiveNctSummaryRead
    latest_activity: list[ExecutiveTransactionRead]
    notifications: list[ExecutiveNotificationRead]


class ExecutiveChartVehicleRead(ExecutiveBaseRead):
    vehicle_id: int
    registration_number: str
    litres: float
    transaction_count: int


class ExecutiveAnalyticsRead(ExecutiveBaseRead):
    range_days: int
    start_date: date
    end_date: date
    labels: list[date]
    diesel_litres: list[float]
    fuel_cost_eur: list[float]
    cost_record_count: list[int]
    transaction_count: list[int]
    top_vehicles: list[ExecutiveChartVehicleRead]
    lowest_vehicles: list[ExecutiveChartVehicleRead]


class ExecutiveVehicleListRead(ExecutiveBaseRead):
    items: list[ExecutiveVehicleRead]
    total: int
    page: int
    page_size: int


class ExecutiveVehicleDetailRead(ExecutiveVehicleRead):
    month_diesel_litres: float
    month_cost_eur: float
    month_cost_record_count: int
    transactions: list[ExecutiveTransactionRead]


class ExecutiveEmployeeRead(ExecutiveBaseRead):
    id: int
    name: str
    is_active: bool
    vehicle_registrations: list[str]
    record_count: int
    diesel_litres: float
    month_record_count: int
    month_diesel_litres: float
    month_cost_eur: float
    month_cost_record_count: int
    latest_activity_at: datetime | None


class ExecutiveEmployeeListRead(ExecutiveBaseRead):
    items: list[ExecutiveEmployeeRead]
    total: int
    page: int
    page_size: int


class ExecutiveEmployeeRecordsRead(ExecutiveBaseRead):
    items: list[ExecutiveTransactionRead]
    total: int
    diesel_litres: float = 0.0
    cost_eur: float = 0.0
    cost_record_count: int = 0
    page: int
    page_size: int


class MyVehicleRead(ExecutiveBaseRead):
    vehicle: ExecutiveVehicleDetailRead | None
    available_vehicles: list[ExecutiveVehicleRead]


class SetMyVehicleRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    vehicle_id: int | None = Field(default=None, gt=0)
