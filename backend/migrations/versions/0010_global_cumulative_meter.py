"""Add persistent state and reset history for the shared PIUSI meter.

Revision ID: 0010_global_cumulative_meter
Revises: 0009_boss_role
Create Date: 2026-11-15
"""
import math
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_global_cumulative_meter"
down_revision: Union[str, None] = "0009_boss_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "global_meter_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("previous_cumulative_total_litres", sa.Float(), nullable=True),
        sa.Column(
            "baseline_cumulative_total_litres", sa.Float(), nullable=False
        ),
        sa.Column("authorized_by_employee_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('reset', 'replacement')",
            name="ck_global_meter_events_event_type",
        ),
        sa.CheckConstraint(
            "baseline_cumulative_total_litres >= 0",
            name="ck_global_meter_events_baseline",
        ),
        sa.ForeignKeyConstraint(
            ["authorized_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_global_meter_events_occurred_at",
        "global_meter_events",
        ["occurred_at", "id"],
    )
    op.create_table(
        "global_meter_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("current_cumulative_total_litres", sa.Float(), nullable=True),
        sa.Column("previous_cumulative_total_litres", sa.Float(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_transaction_id", sa.Integer(), nullable=True),
        sa.Column("last_employee_id", sa.Integer(), nullable=True),
        sa.Column("last_vehicle_id", sa.Integer(), nullable=True),
        sa.Column("last_event_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_global_meter_state_singleton"),
        sa.CheckConstraint(
            "current_cumulative_total_litres IS NULL "
            "OR current_cumulative_total_litres >= 0",
            name="ck_global_meter_state_current_total",
        ),
        sa.CheckConstraint(
            "previous_cumulative_total_litres IS NULL "
            "OR previous_cumulative_total_litres >= 0",
            name="ck_global_meter_state_previous_total",
        ),
        sa.ForeignKeyConstraint(
            ["last_transaction_id"], ["fuel_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["last_employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["last_vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["last_event_id"], ["global_meter_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, created_at, employee_id, vehicle_id, meter_photo_id,
                   cumulative_total_litres, is_demo
            FROM fuel_records
            WHERE cumulative_total_litres IS NOT NULL
              AND cumulative_total_litres >= 0
            ORDER BY created_at DESC, id DESC
            """
        )
    ).mappings().all()
    valid_rows = [
        row
        for row in rows
        if math.isfinite(float(row["cumulative_total_litres"]))
    ]
    if len({row["created_at"] for row in valid_rows}) <= 1:
        valid_rows.sort(
            key=lambda row: (float(row["cumulative_total_litres"]), row["id"]),
            reverse=True,
        )

    latest = valid_rows[0] if valid_rows else None
    previous = valid_rows[1] if len(valid_rows) > 1 else None
    connection.execute(
        sa.text(
            """
            INSERT INTO global_meter_state (
                id,
                current_cumulative_total_litres,
                previous_cumulative_total_litres,
                last_updated_at,
                last_transaction_id,
                last_employee_id,
                last_vehicle_id,
                last_event_id,
                revision
            )
            VALUES (
                1, :current_total, :previous_total, :updated_at,
                :transaction_id, :employee_id, :vehicle_id, NULL, 0
            )
            """
        ),
        {
            "current_total": (
                float(latest["cumulative_total_litres"]) if latest else None
            ),
            "previous_total": (
                float(previous["cumulative_total_litres"]) if previous else None
            ),
            "updated_at": latest["created_at"] if latest else None,
            "transaction_id": latest["id"] if latest else None,
            "employee_id": latest["employee_id"] if latest else None,
            "vehicle_id": latest["vehicle_id"] if latest else None,
        },
    )


def downgrade() -> None:
    op.drop_table("global_meter_state")
    op.drop_index(
        "ix_global_meter_events_occurred_at",
        table_name="global_meter_events",
    )
    op.drop_table("global_meter_events")
