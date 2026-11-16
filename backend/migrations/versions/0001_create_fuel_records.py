"""Create the initial fuel-record table.

Revision ID: 0001_fuel_records
Revises:
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_fuel_records"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fuel_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reg_number", sa.String(length=32), nullable=False),
        sa.Column("fuel_type", sa.String(length=16), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("surname", sa.String(length=100), nullable=False),
        sa.Column("mileage", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Float(), nullable=False),
        sa.Column("litres", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "fuel_type IN ('Diesel', 'AdBlue', 'Petrol')",
            name="ck_fuel_records_fuel_type",
        ),
        sa.CheckConstraint("mileage >= 0", name="ck_fuel_records_mileage"),
        sa.CheckConstraint("capacity > 0", name="ck_fuel_records_capacity"),
        sa.CheckConstraint("litres > 0", name="ck_fuel_records_litres"),
        sa.CheckConstraint("cost >= 0", name="ck_fuel_records_cost"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("fuel_records")
