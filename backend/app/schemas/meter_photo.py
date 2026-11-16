from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.fuel_record import to_camel_case


class QrSessionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    qr_payload: str = Field(min_length=1, max_length=128)


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

    @model_validator(mode="after")
    def require_confirmation(self) -> "MeterPhotoVerify":
        if not self.confirmed:
            raise ValueError("Confirm both readings against the meter before saving.")
        return self
