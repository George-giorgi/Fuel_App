"""Add local employee and vehicle registries.

Revision ID: 0002_employee_vehicle
Revises: 0001_fuel_records
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_employee_vehicle"
down_revision: Union[str, None] = "0001_fuel_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('admin', 'employee')",
            name="ck_employees_role",
        ),
        sa.UniqueConstraint("email", name="uq_employees_email"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("registration_number", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "registration_number",
            name="uq_vehicles_registration_number",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("fuel_records") as batch_op:
        batch_op.add_column(sa.Column("employee_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("vehicle_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_fuel_records_employee_id_employees",
            "employees",
            ["employee_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_fuel_records_vehicle_id_vehicles",
            "vehicles",
            ["vehicle_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("fuel_records") as batch_op:
        batch_op.drop_constraint(
            "fk_fuel_records_vehicle_id_vehicles", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_fuel_records_employee_id_employees", type_="foreignkey"
        )
        batch_op.drop_column("vehicle_id")
        batch_op.drop_column("employee_id")
    op.drop_table("vehicles")
    op.drop_table("employees")
