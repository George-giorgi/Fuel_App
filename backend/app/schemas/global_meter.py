from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from backend.app.schemas.fuel_record import to_camel_case


class GlobalMeterSummaryRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    current_cumulative_total_litres: float | None
    previous_cumulative_total_litres: float | None
    difference_litres: float | None
    current_total_integer: int | None = None
    previous_total_integer: int | None = None
    difference_integer: int | None = None
    current_total_raw_digits: str | None = None
    last_updated_at: datetime | None
    last_transaction_id: int | None
    last_employee_name: str | None
    last_vehicle_registration: str | None
    last_meter_photo_id: int | None
    last_meter_photo_url: str | None
    last_update_source: Literal["fill", "baseline", "reset", "replacement"] | None

    @field_serializer("last_updated_at", when_used="json")
    def serialize_last_updated_at(self, value: datetime | None) -> str | None:
        return _serialize_utc_datetime(value) if value is not None else None


class GlobalMeterHistoryRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    id: str
    kind: Literal["fill", "baseline", "reset", "replacement"]
    created_at: datetime
    previous_cumulative_total_litres: float | None
    current_fill_litres: float | None
    cumulative_total_litres: float
    difference_litres: float | None
    current_fill_milli_litres: int | None = None
    top_current_fill_milli_litres: int | None = None
    cumulative_total_integer: int | None = None
    previous_total_integer: int | None = None
    difference_integer: int | None = None
    reading_source: str | None = None
    fill_source: str | None = None
    warnings: list[str] | None = None
    employee_name: str | None
    vehicle_registration: str | None
    meter_photo_id: int | None
    meter_photo_url: str | None
    status: str
    is_demo: bool
    notes: str | None

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return _serialize_utc_datetime(value)


class GlobalMeterEventCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    event_type: Literal["baseline", "reset", "replacement"]
    baseline_cumulative_total_litres: Decimal = Field(
        ge=0, allow_inf_nan=False, decimal_places=3
    )
    notes: str = Field(min_length=5, max_length=500)


class GlobalMeterEventRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    event_type: Literal["baseline", "reset", "replacement"]
    previous_cumulative_total_litres: float | None
    baseline_cumulative_total_litres: float
    authorized_by_employee_id: int
    occurred_at: datetime
    notes: str
    previous_total_integer: int | None = None
    baseline_total_integer: int | None = None
    previous_total_raw_digits: str | None = None
    baseline_total_raw_digits: str | None = None

    @field_serializer("occurred_at", when_used="json")
    def serialize_occurred_at(self, value: datetime) -> str:
        return _serialize_utc_datetime(value)


def _serialize_utc_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
