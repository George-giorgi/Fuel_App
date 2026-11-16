"""Add vehicle QR sessions and private meter photo metadata.

Revision ID: 0004_qr_sessions_meter_photos
Revises: 0003_single_admin
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_qr_sessions_meter_photos"
down_revision: Union[str, None] = "0003_single_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("qr_token_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_vehicles_qr_token_hash",
        "vehicles",
        ["qr_token_hash"],
        unique=True,
    )
    op.create_table(
        "qr_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_qr_sessions_token_hash",
        "qr_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_qr_sessions_expires_at",
        "qr_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "meter_photos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("qr_session_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["qr_session_id"], ["qr_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_meter_photos_qr_session_id",
        "meter_photos",
        ["qr_session_id"],
        unique=True,
    )
    op.create_index(
        "uq_meter_photos_storage_key",
        "meter_photos",
        ["storage_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_meter_photos_storage_key", table_name="meter_photos")
    op.drop_index("uq_meter_photos_qr_session_id", table_name="meter_photos")
    op.drop_table("meter_photos")
    op.drop_index("ix_qr_sessions_expires_at", table_name="qr_sessions")
    op.drop_index("uq_qr_sessions_token_hash", table_name="qr_sessions")
    op.drop_table("qr_sessions")
    op.drop_index("uq_vehicles_qr_token_hash", table_name="vehicles")
    op.drop_column("vehicles", "qr_token_hash")
