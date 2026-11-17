from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from backend.app.core.config import (
    get_meter_review_threshold_litres,
    get_meter_tolerance_litres,
)


MILLILITRES_PER_LITRE = 1000
MAX_FILL_MILLI_LITRES = 100 * MILLILITRES_PER_LITRE


class InvalidMeterDigits(ValueError):
    pass


@dataclass(frozen=True)
class MeterReadingAssessment:
    fill_milli_litres: int | None
    top_current_fill_milli_litres: int | None
    previous_total_milli_litres: int | None
    cumulative_total_milli_litres: int | None
    delta_milli_litres: int | None
    source: str
    fill_source: str | None
    fill_calculation: str | None
    reconciliation_status: str
    warnings: tuple[str, ...]

    @property
    def requires_review(self) -> bool:
        return bool(self.warnings)


def parse_fill_raw_digits(raw_digits: str | None) -> int | None:
    if raw_digits is None or raw_digits == "":
        return None
    if (
        not raw_digits.isascii()
        or not raw_digits.isdigit()
        or len(raw_digits) > 8
    ):
        raise InvalidMeterDigits("Fill digits must contain only visible digits.")
    fill_milli_litres = int(raw_digits)
    return fill_milli_litres


def parse_total_raw_digits(raw_digits: str | None) -> int | None:
    if raw_digits is None or raw_digits == "":
        return None
    if (
        not raw_digits.isascii()
        or not raw_digits.isdigit()
        or len(raw_digits) > 18
    ):
        raise InvalidMeterDigits(
            "Global total digits must contain only visible digits."
        )
    return int(raw_digits)


def milli_litres_to_decimal(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).scaleb(-3)


def decimal_to_milli_litres(value: Decimal) -> int:
    if (
        not value.is_finite()
        or value < 0
        or value.as_tuple().exponent < -3
    ):
        raise InvalidMeterDigits(
            "Global cumulative total must be non-negative with no more than 3 decimals."
        )
    return int(value * MILLILITRES_PER_LITRE)


def integral_legacy_total(value: int | float | Decimal | None) -> int | None:
    if value is None:
        return None
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None
    if decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)


def assess_meter_readings(
    *,
    fill_milli_litres: int | None,
    previous_total_milli_litres: int | None,
    cumulative_total_milli_litres: int | None,
    source: str,
    tank_capacity_litres: int | float | Decimal | None = None,
) -> MeterReadingAssessment:
    warnings: list[str] = []
    top_current_fill_milli_litres = fill_milli_litres
    delta = (
        cumulative_total_milli_litres - previous_total_milli_litres
        if cumulative_total_milli_litres is not None
        and previous_total_milli_litres is not None
        else None
    )
    calculation: str | None = None
    fill_source: str | None = None

    if cumulative_total_milli_litres is None:
        warnings.append("Global cumulative total is missing or unreadable.")
    if previous_total_milli_litres is None:
        warnings.append(
            "There is no previous global total; this reading establishes the baseline."
        )
    elif delta is not None and delta < 0:
        warnings.append(
            "Global cumulative total decreased; possible reset, replacement, or incorrect reading."
        )
    elif delta == 0:
        warnings.append(
            "Global cumulative total is unchanged; check for a duplicate or unreadable digit."
        )

    fill_milli_litres = None
    if delta is not None and delta > 0:
        fill_milli_litres = delta
        calculation = "global_total_difference"
        fill_source = "GLOBAL_DIFFERENCE"
    if fill_milli_litres is None:
        if top_current_fill_milli_litres is None:
            warnings.append("Fill digits are missing or unreadable.")
    elif fill_milli_litres <= 0:
        warnings.append("Fill must be greater than zero.")
    elif fill_milli_litres > MAX_FILL_MILLI_LITRES:
        warnings.append(
            "Fill exceeds the 100 litre limit; correct the top-row reading."
        )
    if top_current_fill_milli_litres is not None:
        if top_current_fill_milli_litres <= 0:
            warnings.append("Top-row fill must be greater than zero.")
        elif top_current_fill_milli_litres > MAX_FILL_MILLI_LITRES:
            warnings.append(
                "Top-row fill exceeds the 100 litre limit; check the reading."
            )
    if (
        fill_milli_litres is not None
        and tank_capacity_litres is not None
        and Decimal(fill_milli_litres)
        > Decimal(str(tank_capacity_litres)) * MILLILITRES_PER_LITRE
    ):
        warnings.append(
            "Current fill exceeds the configured vehicle tank capacity."
        )
    if (
        top_current_fill_milli_litres is not None
        and tank_capacity_litres is not None
        and Decimal(top_current_fill_milli_litres)
        > Decimal(str(tank_capacity_litres)) * MILLILITRES_PER_LITRE
    ):
        warnings.append(
            "Top-row fill exceeds the configured vehicle tank capacity."
        )

    if delta is not None and delta > (
        get_meter_review_threshold_litres() * MILLILITRES_PER_LITRE
    ):
        warnings.append(
            "Global increase exceeds the configured alert threshold "
            f"({get_meter_review_threshold_litres()} L)."
        )

    if delta is not None and delta > 0 and top_current_fill_milli_litres is not None:
        tolerance_milli_litres = int(
            Decimal(str(get_meter_tolerance_litres()))
            * MILLILITRES_PER_LITRE
        )
        if abs(
            fill_milli_litres - top_current_fill_milli_litres
        ) > tolerance_milli_litres:
            warnings.append(
                "Global difference does not match the top-row fill within "
                f"the {get_meter_tolerance_litres():g} L tolerance."
            )

    warnings = list(dict.fromkeys(warnings))
    if warnings:
        status = "review_required"
    elif calculation:
        status = (
            "reconciled"
            if top_current_fill_milli_litres is not None
            else "calculated"
        )
    elif previous_total_milli_litres is None:
        status = "baseline"
    else:
        status = "reconciled"

    return MeterReadingAssessment(
        fill_milli_litres=fill_milli_litres,
        top_current_fill_milli_litres=top_current_fill_milli_litres,
        previous_total_milli_litres=previous_total_milli_litres,
        cumulative_total_milli_litres=cumulative_total_milli_litres,
        delta_milli_litres=delta,
        source=source,
        fill_source=fill_source,
        fill_calculation=calculation,
        reconciliation_status=status,
        warnings=tuple(warnings),
    )
