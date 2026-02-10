from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models


def create_session(
    db: Session,
    *,
    cv_id: str,
    ui_state_json: dict | None = None,
    active_search_id: str | None = None,
    analysis_executed_at: datetime | None = None,
) -> models.CVSession:
    _deactivate_active_sessions(db)
    now = datetime.utcnow()
    session = models.CVSession(
        cv_id=cv_id,
        active_search_id=active_search_id,
        ui_state_json=ui_state_json or {},
        analysis_executed_at=analysis_executed_at,
        status="active",
        created_at=now,
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return session


def get_current_session(db: Session, *, session_id: str | None = None) -> models.CVSession | None:
    if session_id:
        session = db.get(models.CVSession, session_id)
        if session and session.status != "closed":
            _touch(session)
            db.add(session)
            db.commit()
            db.refresh(session)
            return session

    session = db.scalar(
        select(models.CVSession)
        .where(models.CVSession.status == "active")
        .order_by(desc(models.CVSession.last_seen_at))
    )
    if session:
        _touch(session)
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    session = db.scalar(
        select(models.CVSession)
        .where(models.CVSession.status != "closed")
        .order_by(desc(models.CVSession.last_seen_at))
    )
    if not session:
        return None

    _touch(session)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def resume_session(
    db: Session,
    *,
    session_id: str,
    active_search_id: str | None = None,
    ui_state_json: dict | None = None,
) -> models.CVSession | None:
    session = db.get(models.CVSession, session_id)
    if not session:
        return None

    _deactivate_active_sessions(db, keep_session_id=session.id)
    session.status = "active"
    if active_search_id is not None:
        session.active_search_id = active_search_id
    if ui_state_json is not None:
        session.ui_state_json = ui_state_json
    _touch(session)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def close_session(db: Session, *, session_id: str) -> models.CVSession | None:
    session = db.get(models.CVSession, session_id)
    if not session:
        return None

    session.status = "closed"
    _touch(session)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_session_state(
    db: Session,
    *,
    session_id: str,
    active_search_id: str | None = None,
    ui_state_json: dict | None = None,
) -> models.CVSession | None:
    session = db.get(models.CVSession, session_id)
    if not session or session.status == "closed":
        return None

    if active_search_id is not None:
        session.active_search_id = active_search_id
    if ui_state_json is not None:
        session.ui_state_json = ui_state_json
    _touch(session)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, *, limit: int = 50) -> list[models.CVSession]:
    safe_limit = max(1, min(limit, 200))
    return db.scalars(
        select(models.CVSession).order_by(desc(models.CVSession.created_at)).limit(safe_limit)
    ).all()


def _deactivate_active_sessions(db: Session, *, keep_session_id: str | None = None) -> None:
    active_sessions = db.scalars(
        select(models.CVSession).where(models.CVSession.status == "active")
    ).all()
    for active_session in active_sessions:
        if keep_session_id and active_session.id == keep_session_id:
            continue
        active_session.status = "inactive"
        _touch(active_session)
        db.add(active_session)
    db.flush()


def _touch(session: models.CVSession) -> None:
    session.last_seen_at = datetime.utcnow()
