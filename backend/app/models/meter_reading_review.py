from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class MeterReadingReview(Base):
    __tablename__ = "meter_reading_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_meter_reading_reviews_status",
        ),
        Index(
            "ix_meter_reading_reviews_status_submitted_at",
            "status",
            "submitted_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    meter_photo_id: Mapped[int | None] = mapped_column(
        ForeignKey("meter_photos.id", ondelete="RESTRICT"), nullable=True
    )
    odometer_correction_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicle_odometer_corrections.id", ondelete="RESTRICT"),
        nullable=True,
    )
    odometer_miles: Mapped[float] = mapped_column(Float, nullable=False)
    current_fill_milli_litres: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    top_current_fill_milli_litres: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    cumulative_total_integer: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    previous_global_total_integer: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    current_fill_raw_digits: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    cumulative_total_raw_digits: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    reading_source: Mapped[str] = mapped_column(String(24), nullable=False)
    fill_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    fill_calculation: Mapped[str | None] = mapped_column(String(24), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    global_meter_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fuel_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("fuel_records.id", ondelete="RESTRICT"), nullable=True
    )
    global_meter_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_meter_events.id", ondelete="RESTRICT"), nullable=True
    )
