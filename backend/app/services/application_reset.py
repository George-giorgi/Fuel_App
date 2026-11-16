from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.models import Employee, MeterPhoto


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
