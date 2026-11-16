from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_serializer


def to_camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class FuelRecordRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    reg_number: str
    fuel_type: str
    first_name: str
    surname: str
    mileage_miles: float
    current_odometer_miles: float
    capacity: float
    litres: float
    cost: float
    vehicle_id: int | None
    current_fuel_reading: float | None
    cumulative_meter_reading: float | None
    current_fill_litres: float | None
    cumulative_total_litres: float | None
    meter_delta_litres: float | None
    meter_check_status: str
    meter_epoch: int
    meter_photo_id: int | None
    is_demo: bool
    created_at: datetime

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()


class FuelRecordCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    meter_photo_id: int = Field(gt=0)
    odometer_miles: float = Field(ge=0, allow_inf_nan=False)
    vehicle_id: int | None = Field(default=None, gt=0)
