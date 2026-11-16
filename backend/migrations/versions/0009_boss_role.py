"""Allow boss accounts for vehicle-level dashboard access.

Revision ID: 0009_boss_role
Revises: 0008_vehicle_cumulative_total
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_boss_role"
down_revision: Union[str, None] = "0008_vehicle_cumulative_total"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("employees") as batch_op:
            batch_op.drop_constraint("ck_employees_role", type_="check")
            batch_op.create_check_constraint(
                "ck_employees_role",
                "role IN ('admin', 'employee', 'boss')",
            )
        op.create_index(
            "uq_employees_username_lower",
            "employees",
            [sa.text("lower(username)")],
            unique=True,
        )
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(
                f"Foreign key violations after migration: {violations}"
            )
    finally:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()


def downgrade() -> None:
    connection = op.get_bind()
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("employees") as batch_op:
            batch_op.drop_constraint("ck_employees_role", type_="check")
            batch_op.create_check_constraint(
                "ck_employees_role",
                "role IN ('admin', 'employee')",
            )
        op.create_index(
            "uq_employees_username_lower",
            "employees",
            [sa.text("lower(username)")],
            unique=True,
        )
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(
                f"Foreign key violations after migration: {violations}"
            )
    finally:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
