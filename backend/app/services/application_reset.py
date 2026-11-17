from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterEvent,
    GlobalMeterState,
    MeterPhoto,
    MeterReadingReview,
    QrSession,
    Vehicle,
    VehicleMeterEvent,
    VehicleOdometerCorrection,
)


def reset_application_data(session: Session) -> list[str]:
    administrators = session.scalars(
        select(Employee).where(Employee.role == "admin")
    ).all()
    if len(administrators) != 1:
        raise ValueError(
            "The reset requires exactly one administrator account to preserve."
        )

    photo_keys = list(session.scalars(select(MeterPhoto.storage_key)).all())
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == Employee.__tablename__:
            session.execute(
                delete(table).where(table.c.role != "admin")
            )
        else:
            session.execute(delete(table))

    return photo_keys


def clear_operational_data(session: Session) -> list[str]:
    photo_keys = list(session.scalars(select(MeterPhoto.storage_key)).all())

    for model in (
        GlobalMeterState,
        MeterReadingReview,
        FuelRecord,
        MeterPhoto,
        QrSession,
        GlobalMeterEvent,
        VehicleMeterEvent,
        VehicleOdometerCorrection,
    ):
        session.execute(delete(model))

    session.execute(
        update(Vehicle).values(cumulative_total_litres=None, meter_epoch=0)
    )
    return photo_keys
