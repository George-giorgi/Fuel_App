from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.fuel_record import to_camel_case


class OdometerCorrectionCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    authorized_odometer_miles: float = Field(ge=0, allow_inf_nan=False)
    notes: str = Field(min_length=5, max_length=500)


class OdometerCorrectionRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    vehicle_id: int
    authorized_odometer_miles: float
    previous_odometer_miles: float
    notes: str
    created_at: datetime
    used_at: datetime | None
