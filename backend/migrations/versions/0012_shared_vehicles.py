"""Allow vehicles to be assigned to multiple employees.

Revision ID: 0012_shared_vehicles
Revises: 0011_vehicle_nct_expiry
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_shared_vehicles"
down_revision: Union[str, None] = "0011_vehicle_nct_expiry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        op.create_table(
            "employee_vehicles",
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["employee_id"],
                ["employees.id"],
                name="fk_employee_vehicles_employee_id_employees",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["vehicle_id"],
                ["vehicles.id"],
                name="fk_employee_vehicles_vehicle_id_vehicles",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("employee_id", "vehicle_id"),
        )
        op.create_index(
            "ix_employee_vehicles_vehicle_id",
            "employee_vehicles",
            ["vehicle_id"],
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO employee_vehicles (employee_id, vehicle_id)
                SELECT employee_id, id
                FROM vehicles
                WHERE employee_id IS NOT NULL
                """
            )
        )
        op.drop_index("uq_vehicles_demo_employee_id", table_name="vehicles")
        with op.batch_alter_table("vehicles") as batch_op:
            batch_op.drop_constraint(
                "fk_vehicles_employee_id_employees",
                type_="foreignkey",
            )
            batch_op.drop_column("employee_id")
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(f"Foreign key violations after migration: {violations}")
    finally:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()


def downgrade() -> None:
    connection = op.get_bind()
    shared_vehicles = connection.execute(
        sa.text(
            """
            SELECT vehicle_id
            FROM employee_vehicles
            GROUP BY vehicle_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if shared_vehicles is not None:
        raise RuntimeError(
            "Cannot downgrade while a vehicle is assigned to multiple employees."
        )
    multiple_demo_vehicles = connection.execute(
        sa.text(
            """
            SELECT employee_vehicles.employee_id
            FROM employee_vehicles
            JOIN vehicles ON vehicles.id = employee_vehicles.vehicle_id
            WHERE vehicles.is_demo = 1
            GROUP BY employee_vehicles.employee_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if multiple_demo_vehicles is not None:
        raise RuntimeError(
            "Cannot downgrade while an employee has multiple demo vehicles."
        )

    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("vehicles") as batch_op:
            batch_op.add_column(sa.Column("employee_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_vehicles_employee_id_employees",
                "employees",
                ["employee_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        connection.execute(
            sa.text(
                """
                UPDATE vehicles
                SET employee_id = (
                    SELECT employee_vehicles.employee_id
                    FROM employee_vehicles
                    WHERE employee_vehicles.vehicle_id = vehicles.id
                    LIMIT 1
                )
                """
            )
        )
        op.drop_index(
            "ix_employee_vehicles_vehicle_id",
            table_name="employee_vehicles",
        )
        op.drop_table("employee_vehicles")
        op.create_index(
            "uq_vehicles_demo_employee_id",
            "vehicles",
            ["employee_id"],
            unique=True,
            sqlite_where=sa.text("is_demo = 1"),
        )
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
        if violations:
            raise RuntimeError(f"Foreign key violations after migration: {violations}")
    finally:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
