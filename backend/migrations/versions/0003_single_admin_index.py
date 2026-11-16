"""Ensure the local employee registry has at most one administrator.

Revision ID: 0003_single_admin
Revises: 0002_employee_vehicle
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_single_admin"
down_revision: Union[str, None] = "0002_employee_vehicle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_employees_single_admin",
        "employees",
        ["role"],
        unique=True,
        sqlite_where=sa.text("role = 'admin'"),
        postgresql_where=sa.text("role = 'admin'"),
    )


def downgrade() -> None:
    op.drop_index("uq_employees_single_admin", table_name="employees")
