from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class FuelRecord(Base):
    __tablename__ = "fuel_records"
    __table_args__ = (
        CheckConstraint(
            "fuel_type IN ('Diesel', 'AdBlue', 'Petrol')",
            name="ck_fuel_records_fuel_type",
        ),
        CheckConstraint(
            "mileage_miles >= 0", name="ck_fuel_records_mileage_miles"
        ),
        CheckConstraint("capacity > 0", name="ck_fuel_records_capacity"),
        CheckConstraint("litres > 0", name="ck_fuel_records_litres"),
        CheckConstraint("cost >= 0", name="ck_fuel_records_cost"),
        CheckConstraint(
            "current_fuel_reading IS NULL OR current_fuel_reading >= 0",
            name="ck_fuel_records_current_fuel_reading",
        ),
        CheckConstraint(
            "cumulative_meter_reading IS NULL OR cumulative_meter_reading >= 0",
            name="ck_fuel_records_cumulative_meter_reading",
        ),
        Index("uq_fuel_records_demo_key", "demo_key", unique=True),
        Index("uq_fuel_records_meter_photo_id", "meter_photo_id", unique=True),
        Index(
            "uq_fuel_records_odometer_correction_id",
            "odometer_correction_id",
            unique=True,
        ),
        Index(
            "ix_fuel_records_vehicle_meter_epoch_created_at",
            "vehicle_id",
            "meter_epoch",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reg_number: Mapped[str] = mapped_column(String(32), nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(16), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    surname: Mapped[str] = mapped_column(String(100), nullable=False)
    mileage_miles: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[float] = mapped_column(Float, nullable=False)
    litres: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "employees.id",
            name="fk_fuel_records_employee_id_employees",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "vehicles.id",
            name="fk_fuel_records_vehicle_id_vehicles",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    current_fuel_reading: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_meter_reading: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_fill_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_total_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    meter_delta_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    meter_check_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="legacy", server_default=text("'legacy'")
    )
    meter_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    odometer_correction_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    meter_photo_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "meter_photos.id",
            name="fk_fuel_records_meter_photo_id_meter_photos",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    demo_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    employee: Mapped[Employee | None] = relationship(back_populates="fuel_records")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="fuel_records")
    meter_photo: Mapped[MeterPhoto | None] = relationship()

    @property
    def current_odometer_miles(self) -> float:
        return self.mileage_miles
