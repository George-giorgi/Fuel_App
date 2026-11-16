"""Add demo employee data and revocable employee sessions.

Revision ID: 0005_demo_accounts_sessions
Revises: 0004_qr_sessions_meter_photos
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_demo_accounts_sessions"
down_revision: Union[str, None] = "0004_qr_sessions_meter_photos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _has_foreign_key(
    table_name: str,
    column_name: str,
    referred_table: str,
) -> bool:
    return any(
        foreign_key["constrained_columns"] == [column_name]
        and foreign_key["referred_table"] == referred_table
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def upgrade() -> None:
    connection = op.get_bind()
    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
    try:
        _upgrade_schema()
        if is_sqlite:
            violations = connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).all()
            if violations:
                raise RuntimeError(
                    f"Foreign key violations after migration: {violations}"
                )
    finally:
        if is_sqlite:
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _upgrade_schema() -> None:
    if "username" not in _column_names("employees"):
        op.add_column("employees", sa.Column("username", sa.String(100), nullable=True))
    if "is_demo" not in _column_names("employees"):
        op.add_column(
            "employees",
            sa.Column(
                "is_demo",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )
    if "uq_employees_username_lower" not in _index_names("employees"):
        op.create_index(
            "uq_employees_username_lower",
            "employees",
            [sa.text("lower(username)")],
            unique=True,
        )

    with op.batch_alter_table("vehicles") as batch_op:
        if "employee_id" not in _column_names("vehicles"):
            batch_op.add_column(sa.Column("employee_id", sa.Integer(), nullable=True))
        if not _has_foreign_key("vehicles", "employee_id", "employees"):
            batch_op.create_foreign_key(
                "fk_vehicles_employee_id_employees",
                "employees",
                ["employee_id"],
                ["id"],
                ondelete="RESTRICT",
            )
    for column in (
        sa.Column("make", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("fuel_type", sa.String(16), nullable=True),
        sa.Column("tank_capacity", sa.Float(), nullable=True),
        sa.Column(
            "is_demo",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    ):
        if column.name not in _column_names("vehicles"):
            op.add_column("vehicles", column)
    if "uq_vehicles_demo_employee_id" not in _index_names("vehicles"):
        op.create_index(
            "uq_vehicles_demo_employee_id",
            "vehicles",
            ["employee_id"],
            unique=True,
            sqlite_where=sa.text("is_demo = 1"),
            postgresql_where=sa.true(),
        )

    for column in (
        sa.Column("current_fuel_reading", sa.Float(), nullable=True),
        sa.Column("cumulative_meter_reading", sa.Float(), nullable=True),
        sa.Column(
            "is_demo",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("demo_key", sa.String(100), nullable=True),
    ):
        if column.name not in _column_names("fuel_records"):
            op.add_column("fuel_records", column)
    with op.batch_alter_table("fuel_records") as batch_op:
        if "meter_photo_id" not in _column_names("fuel_records"):
            batch_op.add_column(sa.Column("meter_photo_id", sa.Integer(), nullable=True))
        if not _has_foreign_key(
            "fuel_records", "meter_photo_id", "meter_photos"
        ):
            batch_op.create_foreign_key(
                "fk_fuel_records_meter_photo_id_meter_photos",
                "meter_photos",
                ["meter_photo_id"],
                ["id"],
                ondelete="RESTRICT",
            )
    if "uq_fuel_records_demo_key" not in _index_names("fuel_records"):
        op.create_index(
            "uq_fuel_records_demo_key",
            "fuel_records",
            ["demo_key"],
            unique=True,
        )

    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "employee_sessions" not in table_names:
        op.create_table(
            "employee_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["employee_id"], ["employees.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    for index_name, columns, unique in (
        ("uq_employee_sessions_token_hash", ["token_hash"], True),
        ("ix_employee_sessions_expires_at", ["expires_at"], False),
    ):
        if index_name not in _index_names("employee_sessions"):
            op.create_index(
                index_name,
                "employee_sessions",
                columns,
                unique=unique,
            )


def downgrade() -> None:
    connection = op.get_bind()
    is_sqlite = connection.dialect.name == "sqlite"
    if is_sqlite:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
    try:
        _downgrade_schema()
        if is_sqlite:
            violations = connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).all()
            if violations:
                raise RuntimeError(
                    f"Foreign key violations after downgrade: {violations}"
                )
    finally:
        if is_sqlite:
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _downgrade_schema() -> None:
    op.drop_index("ix_employee_sessions_expires_at", table_name="employee_sessions")
    op.drop_index("uq_employee_sessions_token_hash", table_name="employee_sessions")
    op.drop_table("employee_sessions")

    op.drop_index("uq_fuel_records_demo_key", table_name="fuel_records")
    op.drop_column("fuel_records", "demo_key")
    op.drop_column("fuel_records", "is_demo")
    op.drop_column("fuel_records", "meter_photo_id")
    op.drop_column("fuel_records", "cumulative_meter_reading")
    op.drop_column("fuel_records", "current_fuel_reading")

    op.drop_index("uq_vehicles_demo_employee_id", table_name="vehicles")
    op.drop_column("vehicles", "is_demo")
    op.drop_column("vehicles", "tank_capacity")
    op.drop_column("vehicles", "fuel_type")
    op.drop_column("vehicles", "model")
    op.drop_column("vehicles", "make")
    op.drop_column("vehicles", "employee_id")

    op.drop_index("uq_employees_username_lower", table_name="employees")
    op.drop_column("employees", "is_demo")
    op.drop_column("employees", "username")
