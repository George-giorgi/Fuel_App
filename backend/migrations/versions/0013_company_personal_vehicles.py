"""Classify vehicles as company fleet or personal.

Revision ID: 0013_company_personal_vehicles
Revises: 0012_shared_vehicles
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_company_personal_vehicles"
down_revision: Union[str, None] = "0012_shared_vehicles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "is_company_vehicle",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.drop_column("is_company_vehicle")
