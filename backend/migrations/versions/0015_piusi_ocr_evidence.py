"""Store PIUSI OCR raw digits and recognition evidence.

Revision ID: 0015_piusi_ocr_evidence
Revises: 0014_odometer_miles
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_piusi_ocr_evidence"
down_revision: Union[str, None] = "0014_odometer_miles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("meter_photos")
    }
    new_columns = (
        ("ocr_provider", sa.String(length=32)),
        ("ocr_current_fill_raw_digits", sa.String(length=32)),
        ("ocr_current_fill_decimal_position", sa.Integer()),
        ("ocr_cumulative_total_raw_digits", sa.String(length=32)),
        ("ocr_cumulative_total_decimal_position", sa.Integer()),
        ("ocr_current_fill_segment_confidence", sa.Float()),
        ("ocr_cumulative_total_segment_confidence", sa.Float()),
        ("ocr_warnings", sa.JSON()),
    )
    for name, column_type in new_columns:
        if name not in columns:
            op.add_column(
                "meter_photos",
                sa.Column(name, column_type, nullable=True),
            )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("meter_photos")
    }
    with op.batch_alter_table("meter_photos") as batch_op:
        for name in (
            "ocr_warnings",
            "ocr_cumulative_total_segment_confidence",
            "ocr_current_fill_segment_confidence",
            "ocr_cumulative_total_decimal_position",
            "ocr_cumulative_total_raw_digits",
            "ocr_current_fill_decimal_position",
            "ocr_current_fill_raw_digits",
            "ocr_provider",
        ):
            if name in columns:
                batch_op.drop_column(name)
