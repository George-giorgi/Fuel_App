from datetime import date

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.fuel_record import to_camel_case


class VehicleNctRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    vehicle_id: int
    registration_number: str
    make: str | None
    model: str | None
    employee_name: str | None
    nct_expiry_date: date | None
    days_remaining: int | None
    status: str


class NctAlertsRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    today: date
    expiring_soon_count: int
    expired_count: int
    alerts: list[VehicleNctRead]


class VehicleNctUpdate(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    nct_expiry_date: date | None
