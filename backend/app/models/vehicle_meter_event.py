from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class VehicleMeterEvent(Base):
    __tablename__ = "vehicle_meter_events"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_id", "meter_epoch", name="uq_vehicle_meter_events_epoch"
        ),
        Index("ix_vehicle_meter_events_vehicle_epoch", "vehicle_id", "meter_epoch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    meter_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_cumulative_total_litres: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(String(500), nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="meter_events")
