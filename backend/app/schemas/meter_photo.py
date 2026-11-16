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
    ocr_current_fill_litres: float | None
    ocr_cumulative_total_litres: float | None
    ocr_current_fill_confidence: float | None
    ocr_cumulative_total_confidence: float | None
    ocr_provider: str | None
    ocr_current_fill_raw_digits: str | None
    ocr_current_fill_decimal_position: int | None
    ocr_cumulative_total_raw_digits: str | None
    ocr_cumulative_total_decimal_position: int | None
    ocr_current_fill_segment_confidence: float | None
    ocr_cumulative_total_segment_confidence: float | None
    ocr_warnings: list[str] | None
    current_fill_litres: float | None
    cumulative_total_litres: float | None
    verified_at: datetime | None
    verification_method: str | None
    ocr_message: str | None


class MeterPhotoVerify(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    confirmed: bool
    current_fill_litres: Decimal | None = Field(default=None, gt=0)
    cumulative_total_litres: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_confirmation(self) -> "MeterPhotoVerify":
        if not self.confirmed:
            raise ValueError("Confirm both readings against the meter before saving.")
        if (self.current_fill_litres is None) != (
            self.cumulative_total_litres is None
        ):
            raise ValueError("Enter both meter readings or neither.")
        if (
            self.current_fill_litres is not None
            and not self.current_fill_litres.is_finite()
        ) or (
            self.cumulative_total_litres is not None
            and not self.cumulative_total_litres.is_finite()
        ):
            raise ValueError("Meter readings must be finite numbers.")
        if (
            self.current_fill_litres is not None
            and self.current_fill_litres.as_tuple().exponent < 0
        ):
            raise ValueError("Current Fill must be entered as whole litres.")
        if (
            self.cumulative_total_litres is not None
            and self.cumulative_total_litres.as_tuple().exponent < 0
        ):
            raise ValueError("Cumulative Total must be entered as whole litres.")
        return self
