"""Store odometer readings in miles.

Revision ID: 0014_odometer_miles
Revises: 0013_company_personal_vehicles
Create Date: 2026-11-15
"""
from collections.abc import Callable
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_odometer_miles"
down_revision: Union[str, None] = "0013_company_personal_vehicles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KILOMETRES_PER_MILE = Decimal("1.609344")


def _miles_from_kilometres(value: int | float) -> float:
    return float(
        (Decimal(value) / KILOMETRES_PER_MILE).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


def _kilometres_from_miles(value: int | float) -> int:
    return int(
        (Decimal(str(value)) * KILOMETRES_PER_MILE).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _convert_column(
    table: str,
    source: str,
    target: str,
    converter: Callable[[int | float], float | int],
) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT id, {source} FROM {table} "
            f"WHERE {source} IS NOT NULL AND {target} IS NULL"
        )
    ).all()
    for row_id, value in rows:
        connection.execute(
            sa.text(f"UPDATE {table} SET {target} = :value WHERE id = :id"),
            {"id": row_id, "value": converter(value)},
        )


def _column_info(table: str) -> dict[str, dict[str, object]]:
    return {
        column["name"]: column
        for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def _check_names(table: str) -> set[str | None]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
    }


def _ensure_values_converted(table: str, column: str) -> None:
    null_count = op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            f"Cannot complete the odometer migration: {table}.{column} "
            f"still has {null_count} unconverted value(s)."
        )


def upgrade() -> None:
    fuel_columns = _column_info("fuel_records")
    if "mileage_miles" not in fuel_columns:
        op.add_column(
            "fuel_records",
            sa.Column("mileage_miles", sa.Float(), nullable=True),
        )
        fuel_columns = _column_info("fuel_records")
    if "mileage" in fuel_columns:
        _convert_column(
            "fuel_records", "mileage", "mileage_miles", _miles_from_kilometres
        )
    _ensure_values_converted("fuel_records", "mileage_miles")
    fuel_checks = _check_names("fuel_records")
    if (
        "mileage" in fuel_columns
        or "ck_fuel_records_mileage" in fuel_checks
        or fuel_columns["mileage_miles"]["nullable"]
        or "ck_fuel_records_mileage_miles" not in fuel_checks
    ):
        with op.batch_alter_table("fuel_records") as batch_op:
            if "ck_fuel_records_mileage" in fuel_checks:
                batch_op.drop_constraint("ck_fuel_records_mileage", type_="check")
            if "mileage" in fuel_columns:
                batch_op.drop_column("mileage")
            if fuel_columns["mileage_miles"]["nullable"]:
                batch_op.alter_column(
                    "mileage_miles",
                    existing_type=sa.Float(),
                    nullable=False,
                )
            if "ck_fuel_records_mileage_miles" not in fuel_checks:
                batch_op.create_check_constraint(
                    "ck_fuel_records_mileage_miles", "mileage_miles >= 0"
                )

    correction_columns = _column_info("vehicle_odometer_corrections")
    for column in ("authorized_odometer_miles", "previous_odometer_miles"):
        if column not in correction_columns:
            op.add_column(
                "vehicle_odometer_corrections",
                sa.Column(column, sa.Float(), nullable=True),
            )
    correction_columns = _column_info("vehicle_odometer_corrections")
    for source, target in (
        ("authorized_odometer_km", "authorized_odometer_miles"),
        ("previous_odometer_km", "previous_odometer_miles"),
    ):
        if source in correction_columns:
            _convert_column(
                "vehicle_odometer_corrections",
                source,
                target,
                _miles_from_kilometres,
            )
        _ensure_values_converted("vehicle_odometer_corrections", target)
    if (
        "authorized_odometer_km" in correction_columns
        or "previous_odometer_km" in correction_columns
        or correction_columns["authorized_odometer_miles"]["nullable"]
        or correction_columns["previous_odometer_miles"]["nullable"]
    ):
        with op.batch_alter_table("vehicle_odometer_corrections") as batch_op:
            for column in ("authorized_odometer_km", "previous_odometer_km"):
                if column in correction_columns:
                    batch_op.drop_column(column)
            for column in ("authorized_odometer_miles", "previous_odometer_miles"):
                if correction_columns[column]["nullable"]:
                    batch_op.alter_column(
                        column,
                        existing_type=sa.Float(),
                        nullable=False,
                    )


def downgrade() -> None:
    op.add_column(
        "fuel_records",
        sa.Column("mileage", sa.Integer(), nullable=True),
    )
    _convert_column(
        "fuel_records", "mileage_miles", "mileage", _kilometres_from_miles
    )
    with op.batch_alter_table("fuel_records") as batch_op:
        batch_op.drop_constraint("ck_fuel_records_mileage_miles", type_="check")
        batch_op.drop_column("mileage_miles")
        batch_op.alter_column(
            "mileage",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_fuel_records_mileage", "mileage >= 0"
        )

    op.add_column(
        "vehicle_odometer_corrections",
        sa.Column("authorized_odometer_km", sa.Integer(), nullable=True),
    )
    op.add_column(
        "vehicle_odometer_corrections",
        sa.Column("previous_odometer_km", sa.Integer(), nullable=True),
    )
    _convert_column(
        "vehicle_odometer_corrections",
        "authorized_odometer_miles",
        "authorized_odometer_km",
        _kilometres_from_miles,
    )
    _convert_column(
        "vehicle_odometer_corrections",
        "previous_odometer_miles",
        "previous_odometer_km",
        _kilometres_from_miles,
    )
    with op.batch_alter_table("vehicle_odometer_corrections") as batch_op:
        batch_op.alter_column(
            "authorized_odometer_km",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "previous_odometer_km",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("authorized_odometer_miles")
        batch_op.drop_column("previous_odometer_miles")
