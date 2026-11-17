from datetime import datetime, timezone
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)
from typing import Literal


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
    current_fill_milli_litres: int | None = None
    cumulative_total_integer: int | None = None
    previous_global_total_integer: int | None = None
    cumulative_total_raw_digits: str | None = None
    meter_reading_source: str = "legacy"
    reading_source: str | None = None
    fill_calculation: str | None = None
    meter_check_status: str
    meter_warnings: list[str] | None = None
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

    meter_photo_id: int | None = Field(default=None, gt=0)
    odometer_miles: float = Field(ge=0, allow_inf_nan=False)
    vehicle_id: int | None = Field(default=None, gt=0)
    cumulative_total_litres: Decimal | None = Field(
        default=None, ge=0, allow_inf_nan=False, decimal_places=3
    )
    cumulative_total_raw_digits: str | None = Field(
        default=None, min_length=6, max_length=18
    )
    confirmed: bool = False
    calculated_fill_confirmed: bool = False

    @model_validator(mode="after")
    def validate_meter_readings(self) -> "FuelRecordCreate":
        if self.meter_photo_id is not None:
            if (
                self.cumulative_total_litres is not None
                or self.cumulative_total_raw_digits is not None
                or self.confirmed
            ):
                raise ValueError(
                    "Provide either a verified meter photo or manually entered readings."
                )
            return self

        has_total = (
            self.cumulative_total_litres is not None
            or self.cumulative_total_raw_digits is not None
        )
        if not has_total:
            raise ValueError(
                "Enter global cumulative-total digits when submitting without a photo."
            )
        if not self.confirmed:
            raise ValueError("Confirm the meter readings before submitting.")
        if (
            self.cumulative_total_litres is not None
            and self.cumulative_total_raw_digits is not None
        ):
            raise ValueError("Provide raw digits or a legacy numeric reading, not both.")
        if self.cumulative_total_raw_digits is not None and (
            not self.cumulative_total_raw_digits.isascii()
            or not self.cumulative_total_raw_digits.isdigit()
        ):
            raise ValueError("Global cumulative total must contain digits only.")
        if (
            self.cumulative_total_litres is not None
            and self.cumulative_total_litres.as_tuple().exponent < -3
        ):
            raise ValueError("Legacy total values allow up to 3 decimals.")
        return self


class MeterReadingReviewRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    id: int
    employee_id: int
    vehicle_id: int
    meter_photo_id: int | None
    odometer_miles: float
    current_fill_milli_litres: int | None
    top_current_fill_milli_litres: int | None
    cumulative_total_integer: int | None
    previous_global_total_integer: int | None
    current_fill_raw_digits: str | None
    cumulative_total_raw_digits: str | None
    reading_source: str
    fill_source: str | None
    fill_calculation: str | None
    warnings: list[str]
    status: Literal["pending", "approved", "rejected"]
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_employee_id: int | None
    review_note: str | None
    fuel_record_id: int | None
    global_meter_event_id: int | None


class MeterReadingReviewDecision(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=500)


class FuelRecordSubmissionRead(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    status: Literal["accepted", "review_pending"]
    record: FuelRecordRead | None = None
    review: MeterReadingReviewRead | None = None


class MeterReadingPreviewRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        extra="forbid",
    )

    cumulative_total_raw_digits: str = Field(min_length=6, max_length=18)

    @model_validator(mode="after")
    def validate_digits(self) -> "MeterReadingPreviewRequest":
        value = self.cumulative_total_raw_digits
        if not value.isascii() or not value.isdigit():
            raise ValueError("Meter readings must contain digits only.")
        return self


class MeterReadingPreviewRead(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
    )

    fill_milli_litres: int | None
    previous_total_litres: float | None
    previous_total_milli_litres: int | None = None
    cumulative_total_litres: float
    cumulative_total_milli_litres: int
    delta_litres: float | None
    delta_milli_litres: int | None = None
    fill_calculation: str | None
    fill_source: str | None
    reading_source: str
    reconciliation_status: str
    warnings: list[str]
