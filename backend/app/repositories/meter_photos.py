from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import MeterPhoto, QrSession


def get_qr_session_by_hash(session: Session, token_hash: str) -> QrSession | None:
    return session.scalar(
        select(QrSession).where(QrSession.token_hash == token_hash)
    )


def add_qr_session(session: Session, qr_session: QrSession) -> QrSession:
    session.add(qr_session)
    session.flush()
    return qr_session


def add_meter_photo(session: Session, meter_photo: MeterPhoto) -> MeterPhoto:
    session.add(meter_photo)
    session.flush()
    return meter_photo


def get_meter_photo_by_id(
    session: Session, meter_photo_id: int
) -> MeterPhoto | None:
    return session.get(MeterPhoto, meter_photo_id)
