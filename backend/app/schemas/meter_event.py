from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.fuel_record import to_camel_case


class MeterEventCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["reset", "replacement"]
    baseline_cumulative_total_litres: float = Field(ge=0, allow_inf_nan=False)
    notes: str = Field(min_length=5, max_length=500)
    occurred_at: datetime | None = None


class MeterEventRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    vehicle_id: int
    meter_epoch: int
    event_type: str
    baseline_cumulative_total_litres: float
    occurred_at: datetime
    notes: str
