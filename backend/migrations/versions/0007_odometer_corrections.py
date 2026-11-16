"""Add one-time admin-authorized odometer corrections.

Revision ID: 0007_odometer_corrections
Revises: 0006_meter_readings_ocr
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_odometer_corrections"
down_revision: Union[str, None] = "0006_meter_readings_ocr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    if "vehicle_odometer_corrections" not in _table_names():
        op.create_table(
            "vehicle_odometer_corrections",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("authorized_by_employee_id", sa.Integer(), nullable=False),
            sa.Column("authorized_odometer_km", sa.Integer(), nullable=False),
            sa.Column("previous_odometer_km", sa.Integer(), nullable=False),
            sa.Column("notes", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_by_employee_id", sa.Integer(), nullable=True),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["authorized_by_employee_id"],
                ["employees.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["used_by_employee_id"], ["employees.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if (
        "ix_vehicle_odometer_corrections_vehicle_used"
        not in _index_names("vehicle_odometer_corrections")
    ):
        op.create_index(
            "ix_vehicle_odometer_corrections_vehicle_used",
            "vehicle_odometer_corrections",
            ["vehicle_id", "used_at"],
        )
    if "odometer_correction_id" not in _column_names("fuel_records"):
        op.add_column(
            "fuel_records",
            sa.Column("odometer_correction_id", sa.Integer(), nullable=True),
        )
    if "uq_fuel_records_odometer_correction_id" not in _index_names(
        "fuel_records"
    ):
        op.create_index(
            "uq_fuel_records_odometer_correction_id",
            "fuel_records",
            ["odometer_correction_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index(
        "uq_fuel_records_odometer_correction_id",
        table_name="fuel_records",
    )
    op.drop_column("fuel_records", "odometer_correction_id")
    op.drop_index(
        "ix_vehicle_odometer_corrections_vehicle_used",
        table_name="vehicle_odometer_corrections",
    )
    op.drop_table("vehicle_odometer_corrections")
