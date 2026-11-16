"""Persist each vehicle's cumulative meter total.

Revision ID: 0008_vehicle_cumulative_total
Revises: 0007_odometer_corrections
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_vehicle_cumulative_total"
down_revision: Union[str, None] = "0007_odometer_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("cumulative_total_litres", sa.Float(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE vehicles
            SET cumulative_total_litres = COALESCE(
                (
                    SELECT fuel_records.cumulative_total_litres
                    FROM fuel_records
                    WHERE fuel_records.vehicle_id = vehicles.id
                      AND fuel_records.meter_epoch = vehicles.meter_epoch
                      AND fuel_records.is_demo = 0
                      AND fuel_records.cumulative_total_litres IS NOT NULL
                    ORDER BY fuel_records.created_at DESC, fuel_records.id DESC
                    LIMIT 1
                ),
                (
                    SELECT vehicle_meter_events.baseline_cumulative_total_litres
                    FROM vehicle_meter_events
                    WHERE vehicle_meter_events.vehicle_id = vehicles.id
                      AND vehicle_meter_events.meter_epoch = vehicles.meter_epoch
                    ORDER BY vehicle_meter_events.id DESC
                    LIMIT 1
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("vehicles", "cumulative_total_litres")
