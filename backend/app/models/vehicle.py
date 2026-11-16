from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.employee import employee_vehicles

if TYPE_CHECKING:
    from backend.app.models.employee import Employee
    from backend.app.models.fuel_record import FuelRecord
    from backend.app.models.vehicle_meter_event import VehicleMeterEvent


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint(
            "registration_number",
            name="uq_vehicles_registration_number",
        ),
        Index("uq_vehicles_qr_token_hash", "qr_token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_number: Mapped[str] = mapped_column(String(32), nullable=False)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nct_expiry_date: Mapped[date | None] = mapped_column(nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tank_capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_total_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    meter_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    qr_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    is_company_vehicle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    employees: Mapped[list[Employee]] = relationship(
        secondary=employee_vehicles,
        back_populates="vehicles",
    )
    fuel_records: Mapped[list[FuelRecord]] = relationship(back_populates="vehicle")
    meter_events: Mapped[list[VehicleMeterEvent]] = relationship(
        back_populates="vehicle"
    )

    @property
    def employee_count(self) -> int:
        return len(self.employees)
