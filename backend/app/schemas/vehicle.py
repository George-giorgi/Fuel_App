from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.fuel_record import to_camel_case


class VehicleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    registration_number: str = Field(min_length=1, max_length=32)
    make: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    fuel_type: Literal["Diesel", "AdBlue", "Petrol"] | None = None
    tank_capacity: float | None = Field(default=None, gt=0)
    nct_expiry_date: date | None = None
    is_company_vehicle: bool = True

    @field_validator("registration_number")
    @classmethod
    def normalize_registration(cls, value: str) -> str:
        return value.upper()


class VehicleRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    registration_number: str
    make: str | None
    model: str | None
    fuel_type: str | None
    tank_capacity: float | None
    nct_expiry_date: date | None = None
    meter_epoch: int
    is_active: bool
    is_company_vehicle: bool = True
    employee_count: int = 0
    last_recorded_odometer_miles: float | None = None
    is_demo: bool


class VehicleQrRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    registration_number: str
    qr_payload: str
