from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.fuel_record import to_camel_case


class QrSessionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    qr_payload: str = Field(min_length=1, max_length=128)


class MeterPhotoSessionCreate(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    vehicle_id: int = Field(gt=0)


class MeterPhotoSessionRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel_case, populate_by_name=True)

    session_token: str
    registration_number: str
    expires_at: datetime


class MeterPhotoRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    registration_number: str
    ocr_status: str
    suggested_cumulative_total_raw_digits: str | None = None
    ocr_requires_manual_review: bool = False
    reading_warnings: list[str] | None = None
    cumulative_total_manually_corrected: bool | None = None
    current_fill_litres: float | None
    cumulative_total_litres: float | None
    current_fill_milli_litres: int | None = None
    cumulative_total_integer: int | None = None
    previous_global_total_integer: int | None = None
    reading_source: str | None = None
    fill_source: str | None = None
    fill_calculation: str | None = None
    reconciliation_status: str | None = None
    verified_at: datetime | None
    verification_method: str | None


class MeterPhotoVerify(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    confirmed: bool
    cumulative_total_litres: Decimal | None = Field(
        default=None, ge=0, decimal_places=3
    )
    cumulative_total_raw_digits: str | None = Field(
        default=None, min_length=6, max_length=6
    )

    @model_validator(mode="after")
    def require_confirmation(self) -> "MeterPhotoVerify":
        if not self.confirmed:
            raise ValueError("Confirm the entered meter readings before saving.")
        if self.cumulative_total_litres is not None and self.cumulative_total_raw_digits is not None:
            raise ValueError("Provide raw digits or a legacy numeric reading, not both.")
        if (
            self.cumulative_total_litres is not None
            and not self.cumulative_total_litres.is_finite()
        ):
            raise ValueError("Meter readings must be finite numbers.")
        if (
            self.cumulative_total_litres is not None
            and self.cumulative_total_litres > Decimal("999.999")
        ):
            raise ValueError("Global cumulative total must fit exactly six meter digits.")
        value = self.cumulative_total_raw_digits
        if value is not None and (not value.isascii() or not value.isdigit()):
            raise ValueError("cumulative_total_raw_digits must contain digits only.")
        return self
