from datetime import date
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from backend.app.schemas.auth import EmployeeRead
from backend.app.schemas.fuel_record import to_camel_case
from backend.app.schemas.vehicle import VehicleRead


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Literal["employee", "boss"] = "employee"
    vehicle_id: int | None = Field(default=None, gt=0)
    vehicle_registration_number: str | None = Field(
        default=None, min_length=1, max_length=32
    )
    vehicle_make: str | None = Field(default=None, min_length=1, max_length=100)
    vehicle_model: str | None = Field(default=None, min_length=1, max_length=100)
    vehicle_fuel_type: Literal["Diesel", "AdBlue", "Petrol"] | None = None
    vehicle_tank_capacity: float | None = Field(default=None, gt=0)
    nct_expiry_date: date | None = None
    vehicle_is_company_vehicle: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()

    @field_validator("vehicle_registration_number")
    @classmethod
    def normalize_vehicle_registration(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_vehicle_assignment(self) -> "EmployeeCreate":
        if self.vehicle_id is not None and self.vehicle_registration_number is not None:
            raise ValueError("Choose an existing vehicle or register a new one, not both.")
        has_vehicle_details = any(
            (
                self.vehicle_make is not None,
                self.vehicle_model is not None,
                self.vehicle_fuel_type is not None,
                self.vehicle_tank_capacity is not None,
                self.nct_expiry_date is not None,
            )
        )
        if has_vehicle_details and self.vehicle_registration_number is None:
            raise ValueError("Vehicle details can only be set for a newly registered vehicle.")
        if self.vehicle_id is not None and not self.vehicle_is_company_vehicle:
            raise ValueError(
                "Vehicle classification can only be set for a newly registered vehicle."
            )
        if (
            not self.vehicle_is_company_vehicle
            and self.vehicle_registration_number is None
        ):
            raise ValueError(
                "A personal vehicle classification requires a new vehicle registration."
            )
        return self


class EmployeeRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["employee", "boss"]


class EmployeeStatusUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    is_active: bool


class AdminEmployeeCreatedRead(EmployeeRead):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    assigned_vehicle: VehicleRead | None = None
