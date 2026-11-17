"""Normalize whole-digit meter readings to litres and backfill exact units.

Revision ID: 0018_global_total_millilitres
Revises: 0017_fill_evidence
Create Date: 2026-11-17
"""
from decimal import Decimal, InvalidOperation
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_global_total_millilitres"
down_revision: Union[str, None] = "0017_fill_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


_FLOAT_COLUMNS = {
    "fuel_records": {
        "litres",
        "current_fill_litres",
        "cumulative_meter_reading",
        "cumulative_total_litres",
        "meter_delta_litres",
    },
    "meter_photos": {
        "ocr_current_fill_litres",
        "ocr_cumulative_total_litres",
        "current_fill_litres",
        "cumulative_total_litres",
    },
    "global_meter_state": {
        "current_cumulative_total_litres",
        "previous_cumulative_total_litres",
    },
    "global_meter_events": {
        "previous_cumulative_total_litres",
        "baseline_cumulative_total_litres",
    },
}


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _valid_digits(value: object) -> str | None:
    if isinstance(value, str) and value and value.isascii() and value.isdigit():
        return value
    return None


def _is_whole_digit_storage(value: Decimal | None, raw_digits: object) -> bool:
    digits = _valid_digits(raw_digits)
    return value is not None and digits is not None and value == Decimal(digits)


def _units(value: Decimal | None) -> int | None:
    if value is None or value < 0:
        return None
    milli_litres = value * 1000
    return (
        int(milli_litres)
        if milli_litres == milli_litres.to_integral_value()
        else None
    )


def _columns(connection: sa.Connection, table: str) -> set[str]:
    return {
        column["name"] for column in sa.inspect(connection).get_columns(table)
    }


def _rows(connection: sa.Connection, table: str) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in connection.execute(sa.text(f"SELECT * FROM {table}")).mappings()
    ]


def _update(
    connection: sa.Connection,
    table: str,
    row_id: int,
    values: dict[str, object],
    original: dict[str, object] | None = None,
) -> None:
    if not values:
        return
    if original is not None:
        for column in _FLOAT_COLUMNS.get(table, set()).intersection(values):
            old_value = original.get(column)
            if old_value == values[column]:
                continue
            exists = connection.execute(
                sa.text(
                    """
                    SELECT 1 FROM meter_scale_migration_backup
                    WHERE table_name = :table_name
                        AND row_id = :row_id
                        AND column_name = :column_name
                    """
                ),
                {
                    "table_name": table,
                    "row_id": row_id,
                    "column_name": column,
                },
            ).first()
            if exists is None:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO meter_scale_migration_backup
                            (table_name, row_id, column_name, old_value)
                        VALUES (:table_name, :row_id, :column_name, :old_value)
                        """
                    ),
                    {
                        "table_name": table,
                        "row_id": row_id,
                        "column_name": column,
                        "old_value": old_value,
                    },
                )
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    connection.execute(
        sa.text(f"UPDATE {table} SET {assignments} WHERE id = :row_id"),
        {**values, "row_id": row_id},
    )


def _normalize_photo_rows(connection: sa.Connection) -> dict[int, dict[str, object]]:
    columns = _columns(connection, "meter_photos")
    photos: dict[int, dict[str, object]] = {}
    for row in _rows(connection, "meter_photos"):
        values: dict[str, object] = {}
        manual_correction = row.get("verification_method") == "manual_correction"
        for value_column, raw_column, is_fill in (
            (
                "ocr_current_fill_litres",
                "ocr_current_fill_raw_digits",
                True,
            ),
            (
                "ocr_cumulative_total_litres",
                "ocr_cumulative_total_raw_digits",
                False,
            ),
        ):
            number = _decimal(row.get(value_column))
            raw_digits = row.get(raw_column)
            scaled = _is_whole_digit_storage(number, raw_digits) or (
                is_fill
                and number is not None
                and number > 100
                and number == number.to_integral_value()
            )
            normalized = number / 1000 if scaled and number is not None else number
            if value_column in columns and scaled and normalized is not None:
                values[value_column] = float(normalized)

        final_values: list[tuple[str, str, str, bool]] = [
            (
                "current_fill_litres",
                "current_fill_raw_digits",
                "ocr_current_fill_raw_digits",
                True,
            ),
            (
                "cumulative_total_litres",
                "cumulative_total_raw_digits",
                "ocr_cumulative_total_raw_digits",
                False,
            ),
        ]
        for value_column, result_raw_column, ocr_raw_column, is_fill in final_values:
            number = _decimal(row.get(value_column))
            raw_digits = row.get(result_raw_column)
            if not _valid_digits(raw_digits):
                raw_digits = row.get(ocr_raw_column)
            scaled = _is_whole_digit_storage(number, raw_digits) or (
                is_fill
                and number is not None
                and number > 100
                and number == number.to_integral_value()
            )
            if (
                not is_fill
                and manual_correction
                and number is not None
                and number > 100
                and number == number.to_integral_value()
            ):
                scaled = True
            normalized = number / 1000 if scaled and number is not None else number
            units = _units(normalized)
            if scaled and normalized is not None:
                values[value_column] = float(normalized)
            integer_column = (
                "current_fill_milli_litres"
                if is_fill
                else "cumulative_total_integer"
            )
            if (
                units is not None
                and integer_column in columns
                and row.get(integer_column) is None
            ):
                values[integer_column] = units
            if (
                units is not None
                and result_raw_column in columns
                and row.get(result_raw_column) is None
            ):
                values[result_raw_column] = str(units)
            if (
                is_fill
                and units is not None
                and "top_current_fill_milli_litres" in columns
                and row.get("top_current_fill_milli_litres") is None
            ):
                values["top_current_fill_milli_litres"] = units
            if units is not None:
                row[integer_column] = row.get(integer_column) or units
                row[result_raw_column] = row.get(result_raw_column) or str(units)
        _update(connection, "meter_photos", int(row["id"]), values, row)
        photos[int(row["id"])] = {**row, **values}
    return photos


def _normalize_fuel_rows(
    connection: sa.Connection,
    photos: dict[int, dict[str, object]],
) -> dict[int, dict[str, object]]:
    columns = _columns(connection, "fuel_records")
    records: dict[int, dict[str, object]] = {}
    for row in _rows(connection, "fuel_records"):
        photo = photos.get(row.get("meter_photo_id"))
        values: dict[str, object] = {}
        manual_correction = (
            photo is not None
            and photo.get("verification_method") == "manual_correction"
        )

        fill_raw = row.get("current_fill_raw_digits")
        if not _valid_digits(fill_raw) and photo is not None:
            fill_raw = photo.get("ocr_current_fill_raw_digits")
        fill_number = _decimal(
            row.get("current_fill_litres")
            if row.get("current_fill_litres") is not None
            else row.get("litres")
        )
        fill_scaled = _is_whole_digit_storage(fill_number, fill_raw) or (
            fill_number is not None
            and fill_number > 100
            and fill_number == fill_number.to_integral_value()
        )
        normalized_fill = (
            fill_number / 1000 if fill_scaled and fill_number is not None else fill_number
        )
        fill_units = _units(normalized_fill)
        for column in ("current_fill_litres", "litres"):
            number = _decimal(row.get(column))
            if number is not None:
                column_scaled = _is_whole_digit_storage(number, fill_raw) or (
                    number > 100 and number == number.to_integral_value()
                )
                if column_scaled:
                    values[column] = float(number / 1000)
        if (
            fill_units is not None
            and "current_fill_milli_litres" in columns
            and row.get("current_fill_milli_litres") is None
        ):
            values["current_fill_milli_litres"] = fill_units
        if (
            fill_units is not None
            and "top_current_fill_milli_litres" in columns
            and row.get("top_current_fill_milli_litres") is None
        ):
            values["top_current_fill_milli_litres"] = fill_units
        if (
            fill_units is not None
            and "current_fill_raw_digits" in columns
            and row.get("current_fill_raw_digits") is None
        ):
            values["current_fill_raw_digits"] = str(fill_units)

        total_raw = row.get("cumulative_total_raw_digits")
        photo_total_raw = (
            photo.get("ocr_cumulative_total_raw_digits")
            if photo is not None
            else None
        )
        if not _valid_digits(total_raw):
            total_raw = photo_total_raw
        total_number = _decimal(row.get("cumulative_total_litres"))
        total_scaled = _is_whole_digit_storage(total_number, total_raw) or (
            manual_correction
            and total_number is not None
            and total_number > 100
            and total_number == total_number.to_integral_value()
        )
        normalized_total = (
            total_number / 1000
            if total_scaled and total_number is not None
            else total_number
        )
        total_units = _units(normalized_total)
        for column in ("cumulative_meter_reading", "cumulative_total_litres"):
            number = _decimal(row.get(column))
            if number is not None:
                column_scaled = _is_whole_digit_storage(number, total_raw) or (
                    manual_correction
                    and number > 100
                    and number == number.to_integral_value()
                )
                if column_scaled:
                    values[column] = float(number / 1000)
        if total_scaled:
            delta = _decimal(row.get("meter_delta_litres"))
            if delta is not None:
                values["meter_delta_litres"] = float(delta / 1000)
        if (
            total_units is not None
            and "cumulative_total_integer" in columns
            and row.get("cumulative_total_integer") is None
        ):
            values["cumulative_total_integer"] = total_units
        if (
            total_units is not None
            and "cumulative_total_raw_digits" in columns
            and row.get("cumulative_total_raw_digits") is None
        ):
            values["cumulative_total_raw_digits"] = str(total_units)
        if fill_units is not None and row.get("current_fill_milli_litres") is None:
            row["current_fill_milli_litres"] = fill_units
        if total_units is not None:
            row["cumulative_total_integer"] = (
                row.get("cumulative_total_integer") or total_units
            )
            row["cumulative_total_raw_digits"] = (
                row.get("cumulative_total_raw_digits") or str(total_units)
            )
        if fill_units is not None:
            row["current_fill_milli_litres"] = (
                row.get("current_fill_milli_litres") or fill_units
            )
        _update(connection, "fuel_records", int(row["id"]), values, row)
        records[int(row["id"])] = {**row, **values}
    return records


def _normalize_related_rows(
    connection: sa.Connection,
    table: str,
    value_columns: tuple[tuple[str, str], ...],
) -> None:
    columns = _columns(connection, table)
    for row in _rows(connection, table):
        values: dict[str, object] = {}
        for value_column, raw_column in value_columns:
            number = _decimal(row.get(value_column))
            raw = row.get(raw_column)
            scaled = _is_whole_digit_storage(number, raw)
            normalized = number / 1000 if scaled and number is not None else number
            if scaled and normalized is not None:
                values[value_column] = float(normalized)
            integer_column = (
                "current_total_integer"
                if value_column == "current_cumulative_total_litres"
                else "previous_total_integer"
                if value_column == "previous_cumulative_total_litres"
                else "baseline_total_integer"
                if value_column == "baseline_cumulative_total_litres"
                else "previous_total_integer"
            )
            if (
                integer_column in columns
                and row.get(integer_column) is None
                and normalized is not None
            ):
                units = _units(normalized)
                if units is not None:
                    values[integer_column] = units
        _update(connection, table, int(row["id"]), values, row)


def _find_known_total(
    value: object,
    records: dict[int, dict[str, object]],
    events: list[dict[str, object]],
) -> tuple[Decimal, int, str] | None:
    number = _decimal(value)
    if number is None:
        return None
    known_totals = [
        (
            row.get("cumulative_total_litres"),
            row.get("cumulative_total_integer"),
            row.get("cumulative_total_raw_digits"),
        )
        for row in records.values()
    ] + [
        (
            row.get("baseline_cumulative_total_litres"),
            row.get("baseline_total_integer"),
            row.get("baseline_total_raw_digits"),
        )
        for row in events
    ]
    for _, integer, raw_digits in known_totals:
        digits = _valid_digits(raw_digits)
        if digits is not None and number == Decimal(digits):
            units = int(digits)
            return Decimal(units).scaleb(-3), units, digits
    for normalized, integer, raw_digits in known_totals:
        normalized_value = _decimal(normalized)
        if normalized_value is not None and number == normalized_value:
            units = integer if integer is not None else _units(normalized_value)
            if units is not None:
                digits = _valid_digits(raw_digits) or str(units)
                return normalized_value, int(units), digits
    return None


def upgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "meter_scale_migration_backup",
        sa.Column("table_name", sa.String(length=32), nullable=False),
        sa.Column("row_id", sa.BigInteger(), nullable=False),
        sa.Column("column_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint(
            "table_name", "row_id", "column_name",
            name="pk_meter_scale_migration_backup",
        ),
    )
    photos = _normalize_photo_rows(connection)
    records = _normalize_fuel_rows(connection, photos)

    _normalize_related_rows(
        connection,
        "global_meter_state",
        (
            ("current_cumulative_total_litres", "current_total_raw_digits"),
            ("previous_cumulative_total_litres", "previous_total_raw_digits"),
        ),
    )
    _normalize_related_rows(
        connection,
        "global_meter_events",
        (
            ("previous_cumulative_total_litres", "previous_total_raw_digits"),
            ("baseline_cumulative_total_litres", "baseline_total_raw_digits"),
        ),
    )
    events = _rows(connection, "global_meter_events")
    state_columns = _columns(connection, "global_meter_state")
    for state in _rows(connection, "global_meter_state"):
        record = records.get(state.get("last_transaction_id"))
        values: dict[str, object] = {}
        if record is not None:
            for state_column, record_column in (
                ("current_cumulative_total_litres", "cumulative_total_litres"),
                ("current_total_integer", "cumulative_total_integer"),
                ("current_total_raw_digits", "cumulative_total_raw_digits"),
            ):
                if state_column in state_columns:
                    values[state_column] = record.get(record_column)
        if (
            "previous_total_integer" in state_columns
            and state.get("previous_total_integer") is None
        ):
            previous = _find_known_total(
                state.get("previous_cumulative_total_litres"),
                records,
                events,
            )
            if previous is not None:
                previous_litres, previous_integer, previous_digits = previous
                values.update(
                    {
                        "previous_cumulative_total_litres": float(
                            previous_litres
                        ),
                        "previous_total_integer": previous_integer,
                        "previous_total_raw_digits": previous_digits,
                    }
                )
        if values:
            _update(
                connection,
                "global_meter_state",
                int(state["id"]),
                values,
                state,
            )

    photo_columns = _columns(connection, "meter_photos")
    if "ocr_cumulative_total_raw_digits" in photo_columns and (
        "ocr_cumulative_total_decimal_position" in photo_columns
    ):
        for photo in _rows(connection, "meter_photos"):
            digits = _valid_digits(photo.get("ocr_cumulative_total_raw_digits"))
            if digits is not None:
                connection.execute(
                    sa.text(
                        """
                        UPDATE meter_photos
                        SET ocr_cumulative_total_decimal_position = :position
                        WHERE id = :photo_id
                        """
                    ),
                    {
                        "position": max(0, len(digits) - 3),
                        "photo_id": photo["id"],
                    },
                )


def downgrade() -> None:
    connection = op.get_bind()
    if "meter_scale_migration_backup" not in sa.inspect(connection).get_table_names():
        return
    for row in _rows(connection, "meter_scale_migration_backup"):
        connection.execute(
            sa.text(
                f"UPDATE {row['table_name']} SET {row['column_name']} = :old_value "
                "WHERE id = :row_id"
            ),
            {"old_value": row["old_value"], "row_id": row["row_id"]},
        )
    op.drop_table("meter_scale_migration_backup")
