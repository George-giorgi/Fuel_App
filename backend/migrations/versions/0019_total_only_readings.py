"""Store cumulative reading review separately from OCR evidence.

Revision ID: 0019_total_only_readings
Revises: 0018_global_total_millilitres
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_total_only_readings"
down_revision: Union[str, None] = "0018_global_total_millilitres"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "meter_photos",
        sa.Column("reading_warnings", sa.JSON(), nullable=True),
    )
    op.add_column(
        "meter_photos",
        sa.Column(
            "cumulative_total_manually_corrected",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("meter_photos", "cumulative_total_manually_corrected")
    op.drop_column("meter_photos", "reading_warnings")
