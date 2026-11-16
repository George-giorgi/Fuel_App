from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class GlobalMeterEvent(Base):
    __tablename__ = "global_meter_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('reset', 'replacement')",
            name="ck_global_meter_events_event_type",
        ),
        CheckConstraint(
            "baseline_cumulative_total_litres >= 0",
            name="ck_global_meter_events_baseline",
        ),
        Index("ix_global_meter_events_occurred_at", "occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_cumulative_total_litres: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    baseline_cumulative_total_litres: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    authorized_by_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[str] = mapped_column(String(500), nullable=False)


class GlobalMeterState(Base):
    __tablename__ = "global_meter_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_global_meter_state_singleton"),
        CheckConstraint(
            "current_cumulative_total_litres IS NULL "
            "OR current_cumulative_total_litres >= 0",
            name="ck_global_meter_state_current_total",
        ),
        CheckConstraint(
            "previous_cumulative_total_litres IS NULL "
            "OR previous_cumulative_total_litres >= 0",
            name="ck_global_meter_state_previous_total",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    current_cumulative_total_litres: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    previous_cumulative_total_litres: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("fuel_records.id", ondelete="RESTRICT"), nullable=True
    )
    last_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    last_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=True
    )
    last_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_meter_events.id", ondelete="RESTRICT"), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
