"""Separate calculated fills from top-row evidence.

Revision ID: 0017_global_fill_source_and_top_evidence
Revises: 0016_piusi_exact_readings_and_reviews
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_global_fill_source_and_top_evidence"
down_revision: Union[str, None] = "0016_piusi_exact_readings_and_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    additions = {
        "fuel_records": (
            ("top_current_fill_milli_litres", sa.Integer()),
            ("reading_source", sa.String(length=24)),
            ("meter_warnings", sa.JSON()),
        ),
        "meter_photos": (
            ("top_current_fill_milli_litres", sa.Integer()),
            ("fill_source", sa.String(length=24)),
        ),
        "meter_reading_reviews": (
            ("top_current_fill_milli_litres", sa.Integer()),
            ("fill_source", sa.String(length=24)),
            ("global_meter_event_id", sa.Integer()),
        ),
    }
    for table, columns in additions.items():
        existing = {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)
        }
        for name, column_type in columns:
            if name not in existing:
                column = sa.Column(
                    name,
                    column_type,
                    *(
                        [
                            sa.ForeignKey(
                                "global_meter_events.id",
                                name="fk_meter_reading_reviews_global_meter_event_id_global_meter_events",
                                ondelete="RESTRICT",
                            )
                        ]
                        if name == "global_meter_event_id"
                        else []
                    ),
                    nullable=True,
                )
                if name == "global_meter_event_id":
                    with op.batch_alter_table(table) as batch_op:
                        batch_op.add_column(column)
                else:
                    op.add_column(table, column)

    with op.batch_alter_table("fuel_records") as batch_op:
        batch_op.alter_column(
            "meter_reading_source",
            existing_type=sa.String(length=16),
            type_=sa.String(length=24),
            existing_nullable=False,
        )
    with op.batch_alter_table("global_meter_events") as batch_op:
        batch_op.drop_constraint(
            "ck_global_meter_events_event_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_global_meter_events_event_type",
            "event_type IN ('baseline', 'reset', 'replacement')",
        )


def downgrade() -> None:
    with op.batch_alter_table("global_meter_events") as batch_op:
        batch_op.drop_constraint(
            "ck_global_meter_events_event_type",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_global_meter_events_event_type",
            "event_type IN ('reset', 'replacement')",
        )
    for table, columns in (
        (
            "meter_reading_reviews",
            (
                "global_meter_event_id",
                "fill_source",
                "top_current_fill_milli_litres",
            ),
        ),
        ("meter_photos", ("fill_source", "top_current_fill_milli_litres")),
        (
            "fuel_records",
            (
                "meter_warnings",
                "reading_source",
                "top_current_fill_milli_litres",
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
