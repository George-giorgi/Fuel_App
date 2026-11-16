"""Add vehicle NCT expiry dates.

Revision ID: 0011_vehicle_nct_expiry
Revises: 0010_global_cumulative_meter
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_vehicle_nct_expiry"
down_revision: Union[str, None] = "0010_global_cumulative_meter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("nct_expiry_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "nct_expiry_date")
