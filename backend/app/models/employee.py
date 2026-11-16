from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.employee_session import EmployeeSession
    from backend.app.models.fuel_record import FuelRecord
    from backend.app.models.vehicle import Vehicle


employee_vehicles = Table(
    "employee_vehicles",
    Base.metadata,
    Column(
        "employee_id",
        Integer,
        ForeignKey(
            "employees.id",
            name="fk_employee_vehicles_employee_id_employees",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    ),
    Column(
        "vehicle_id",
        Integer,
        ForeignKey(
            "vehicles.id",
            name="fk_employee_vehicles_vehicle_id_vehicles",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    ),
    Index("ix_employee_vehicles_vehicle_id", "vehicle_id"),
)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'employee', 'boss')",
            name="ck_employees_role",
        ),
        UniqueConstraint("email", name="uq_employees_email"),
        Index(
            "uq_employees_username_lower",
            text("lower(username)"),
            unique=True,
        ),
        Index(
            "uq_employees_single_admin",
            "role",
            unique=True,
            sqlite_where=text("role = 'admin'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(
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

    vehicles: Mapped[list[Vehicle]] = relationship(
        secondary=employee_vehicles,
        back_populates="employees",
    )
    fuel_records: Mapped[list[FuelRecord]] = relationship(back_populates="employee")
    sessions: Mapped[list[EmployeeSession]] = relationship(back_populates="employee")
