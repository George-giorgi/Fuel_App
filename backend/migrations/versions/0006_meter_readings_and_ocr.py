"""Add explicit meter readings, OCR review, and meter events.

Revision ID: 0006_meter_readings_ocr
Revises: 0005_demo_accounts_sessions
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_meter_readings_ocr"
down_revision: Union[str, None] = "0005_demo_accounts_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fuel_records",
        sa.Column("current_fill_litres", sa.Float(), nullable=True),
    )
    op.add_column(
        "fuel_records",
        sa.Column("cumulative_total_litres", sa.Float(), nullable=True),
    )
    op.add_column(
        "fuel_records",
        sa.Column("meter_delta_litres", sa.Float(), nullable=True),
    )
    op.add_column(
        "fuel_records",
        sa.Column(
            "meter_check_status",
            sa.String(length=20),
            server_default=sa.text("'legacy'"),
            nullable=False,
        ),
    )
    op.add_column(
        "fuel_records",
        sa.Column(
            "meter_epoch",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE fuel_records SET current_fill_litres = litres "
        "WHERE current_fill_litres IS NULL"
    )
    op.execute(
        "UPDATE fuel_records SET cumulative_total_litres = cumulative_meter_reading "
        "WHERE cumulative_total_litres IS NULL "
        "AND cumulative_meter_reading IS NOT NULL"
    )
    op.create_index(
        "ix_fuel_records_vehicle_meter_epoch_created_at",
        "fuel_records",
        ["vehicle_id", "meter_epoch", "created_at"],
    )
    op.create_index(
        "uq_fuel_records_meter_photo_id",
        "fuel_records",
        ["meter_photo_id"],
        unique=True,
    )

    op.add_column(
        "vehicles",
        sa.Column(
            "meter_epoch",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    for column in (
        sa.Column(
            "ocr_status",
            sa.String(length=20),
            server_default=sa.text("'not_processed'"),
            nullable=False,
        ),
        sa.Column("ocr_current_fill_litres", sa.Float(), nullable=True),
        sa.Column("ocr_cumulative_total_litres", sa.Float(), nullable=True),
        sa.Column("ocr_current_fill_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_cumulative_total_confidence", sa.Float(), nullable=True),
        sa.Column("current_fill_litres", sa.Float(), nullable=True),
        sa.Column("cumulative_total_litres", sa.Float(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified_by_employee_id",
            sa.Integer(),
            sa.ForeignKey(
                "employees.id",
                name="fk_meter_photos_verified_by_employee_id_employees",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("verification_method", sa.String(length=24), nullable=True),
        sa.Column("ocr_message", sa.String(length=255), nullable=True),
    ):
        op.add_column("meter_photos", column)

    op.create_table(
        "vehicle_meter_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("created_by_employee_id", sa.Integer(), nullable=False),
        sa.Column("meter_epoch", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("baseline_cumulative_total_litres", sa.Float(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "vehicle_id", "meter_epoch", name="uq_vehicle_meter_events_epoch"
        ),
    )
    op.create_index(
        "ix_vehicle_meter_events_vehicle_epoch",
        "vehicle_meter_events",
        ["vehicle_id", "meter_epoch"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vehicle_meter_events_vehicle_epoch", table_name="vehicle_meter_events"
    )
    op.drop_table("vehicle_meter_events")

    with op.batch_alter_table("meter_photos") as batch_op:
        batch_op.drop_constraint(
            "fk_meter_photos_verified_by_employee_id_employees",
            type_="foreignkey",
        )
    for column_name in (
        "ocr_message",
        "verification_method",
        "verified_by_employee_id",
        "verified_at",
        "cumulative_total_litres",
        "current_fill_litres",
        "ocr_cumulative_total_confidence",
        "ocr_current_fill_confidence",
        "ocr_cumulative_total_litres",
        "ocr_current_fill_litres",
        "ocr_status",
    ):
        op.drop_column("meter_photos", column_name)

    op.drop_column("vehicles", "meter_epoch")
    op.drop_index("uq_fuel_records_meter_photo_id", table_name="fuel_records")
    op.drop_index(
        "ix_fuel_records_vehicle_meter_epoch_created_at",
        table_name="fuel_records",
    )
    for column_name in (
        "meter_epoch",
        "meter_check_status",
        "meter_delta_litres",
        "cumulative_total_litres",
        "current_fill_litres",
    ):
        op.drop_column("fuel_records", column_name)
