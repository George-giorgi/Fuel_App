"""Retain separate PIUSI OCR candidates for manual review.

Revision ID: 0020_piusi_candidate_evidence
Revises: 0019_total_only_readings
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_piusi_candidate_evidence"
down_revision: Union[str, None] = "0019_total_only_readings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meter_photos",
        sa.Column("ocr_cumulative_total_segment_raw_digits", sa.String(32)),
    )
    op.add_column(
        "meter_photos",
        sa.Column("suggested_cumulative_total_raw_digits", sa.String(32)),
    )


def downgrade() -> None:
    op.drop_column("meter_photos", "suggested_cumulative_total_raw_digits")
    op.drop_column("meter_photos", "ocr_cumulative_total_segment_raw_digits")
