"""Store exact PIUSI readings and pending review evidence.

Revision ID: 0016_piusi_exact_readings_and_reviews
Revises: 0015_piusi_ocr_evidence
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_piusi_exact_readings_and_reviews"
down_revision: Union[str, None] = "0015_piusi_ocr_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table, columns in (
        (
            "fuel_records",
            (
                ("current_fill_milli_litres", sa.Integer()),
                ("cumulative_total_integer", sa.BigInteger()),
                ("previous_global_total_integer", sa.BigInteger()),
                ("current_fill_raw_digits", sa.String(length=32)),
                ("cumulative_total_raw_digits", sa.String(length=32)),
                (
                    "meter_reading_source",
                    sa.String(length=16),
                ),
                ("fill_calculation", sa.String(length=24)),
            ),
        ),
        (
            "meter_photos",
            (
                ("current_fill_milli_litres", sa.Integer()),
                ("cumulative_total_integer", sa.BigInteger()),
                ("previous_global_total_integer", sa.BigInteger()),
                ("current_fill_raw_digits", sa.String(length=32)),
                ("cumulative_total_raw_digits", sa.String(length=32)),
                ("reading_source", sa.String(length=16)),
                ("fill_calculation", sa.String(length=24)),
                ("reconciliation_status", sa.String(length=24)),
            ),
        ),
        (
            "global_meter_state",
            (
                ("current_total_integer", sa.BigInteger()),
                ("previous_total_integer", sa.BigInteger()),
                ("current_total_raw_digits", sa.String(length=32)),
            ),
        ),
        (
            "global_meter_events",
            (
                ("previous_total_integer", sa.BigInteger()),
                ("baseline_total_integer", sa.BigInteger()),
                ("previous_total_raw_digits", sa.String(length=32)),
                ("baseline_total_raw_digits", sa.String(length=32)),
            ),
        ),
    ):
        existing = {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
        }
        for name, column_type in columns:
            if name not in existing:
                op.add_column(
                    table,
                    sa.Column(
                        name,
                        column_type,
                        nullable=(name != "meter_reading_source"),
                        server_default=(
                            sa.text("'legacy'")
                            if name == "meter_reading_source"
                            else None
                        ),
                    ),
                )
                if name == "meter_reading_source":
                    with op.batch_alter_table(table) as batch_op:
                        batch_op.alter_column(
                            name,
                            existing_type=column_type,
                            server_default=None,
                        )

    inspector = sa.inspect(op.get_bind())
    if "meter_reading_reviews" not in inspector.get_table_names():
        op.create_table(
            "meter_reading_reviews",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("meter_photo_id", sa.Integer(), nullable=True),
            sa.Column("odometer_correction_id", sa.Integer(), nullable=True),
            sa.Column("odometer_miles", sa.Float(), nullable=False),
            sa.Column("current_fill_milli_litres", sa.Integer(), nullable=True),
            sa.Column("cumulative_total_integer", sa.BigInteger(), nullable=True),
            sa.Column("previous_global_total_integer", sa.BigInteger(), nullable=True),
            sa.Column("current_fill_raw_digits", sa.String(length=32), nullable=True),
            sa.Column("cumulative_total_raw_digits", sa.String(length=32), nullable=True),
            sa.Column("reading_source", sa.String(length=16), nullable=False),
            sa.Column("fill_calculation", sa.String(length=24), nullable=True),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("global_meter_revision", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by_employee_id", sa.Integer(), nullable=True),
            sa.Column("review_note", sa.String(length=500), nullable=True),
            sa.Column("fuel_record_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["employee_id"], ["employees.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["meter_photo_id"], ["meter_photos.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["odometer_correction_id"],
                ["vehicle_odometer_corrections.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["reviewed_by_employee_id"], ["employees.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["fuel_record_id"], ["fuel_records.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "status IN ('pending', 'approved', 'rejected')",
                name="ck_meter_reading_reviews_status",
            ),
        )
        op.create_index(
            "ix_meter_reading_reviews_status_submitted_at",
            "meter_reading_reviews",
            ["status", "submitted_at"],
        )


def downgrade() -> None:
    if "meter_reading_reviews" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index(
            "ix_meter_reading_reviews_status_submitted_at",
            table_name="meter_reading_reviews",
        )
        op.drop_table("meter_reading_reviews")

    for table, columns in (
        (
            "global_meter_state",
            ("current_total_raw_digits", "previous_total_integer", "current_total_integer"),
        ),
        (
            "global_meter_events",
            (
                "baseline_total_raw_digits",
                "previous_total_raw_digits",
                "baseline_total_integer",
                "previous_total_integer",
            ),
        ),
        (
            "meter_photos",
            (
                "reconciliation_status",
                "fill_calculation",
                "reading_source",
                "cumulative_total_raw_digits",
                "current_fill_raw_digits",
                "previous_global_total_integer",
                "cumulative_total_integer",
                "current_fill_milli_litres",
            ),
        ),
        (
            "fuel_records",
            (
                "fill_calculation",
                "meter_reading_source",
                "cumulative_total_raw_digits",
                "current_fill_raw_digits",
                "previous_global_total_integer",
                "cumulative_total_integer",
                "current_fill_milli_litres",
            ),
        ),
    ):
        existing = {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
        }
        for name in columns:
            if name in existing:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_column(name)
