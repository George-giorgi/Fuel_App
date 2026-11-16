from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class MeterPhoto(Base):
    __tablename__ = "meter_photos"
    __table_args__ = (
        Index("uq_meter_photos_qr_session_id", "qr_session_id", unique=True),
        Index("uq_meter_photos_storage_key", "storage_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    qr_session_id: Mapped[int] = mapped_column(
        ForeignKey("qr_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ocr_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_processed",
        server_default=text("'not_processed'"),
    )
    ocr_current_fill_litres: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    ocr_cumulative_total_litres: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    ocr_current_fill_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    ocr_cumulative_total_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    current_fill_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_total_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "employees.id",
            name="fk_meter_photos_verified_by_employee_id_employees",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    verification_method: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ocr_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
