from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.schemas import (
    SessionCloseIn,
    SessionCurrentOut,
    SessionHistoryOut,
    SessionOut,
    SessionResumeIn,
    SessionStateUpdateIn,
)
from app.services.session_service import (
    close_session,
    get_current_session,
    list_sessions,
    resume_session,
    update_session_state,
)

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/current", response_model=SessionCurrentOut)
def get_current(
    session_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SessionCurrentOut:
    session = get_current_session(db, session_id=session_id)
    if not session:
        return SessionCurrentOut(session=None)
    return SessionCurrentOut(session=_to_session_out(session))


@router.get("/history", response_model=SessionHistoryOut)
def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SessionHistoryOut:
    sessions = list_sessions(db, limit=limit)
    return SessionHistoryOut(items=[_to_session_out(item) for item in sessions])


@router.post("/resume", response_model=SessionOut)
def resume(payload: SessionResumeIn, db: Session = Depends(get_db)) -> SessionOut:
    target = db.get(models.CVSession, payload.session_id)
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    _validate_search_for_session(db, target.cv_id, payload.active_search_id)

    session = resume_session(
        db,
        session_id=payload.session_id,
        active_search_id=payload.active_search_id,
        ui_state_json=payload.ui_state,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_session_out(session)


@router.post("/state", response_model=SessionOut)
def update_state(payload: SessionStateUpdateIn, db: Session = Depends(get_db)) -> SessionOut:
    target = db.get(models.CVSession, payload.session_id)
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    _validate_search_for_session(db, target.cv_id, payload.active_search_id)

    session = update_session_state(
        db,
        session_id=payload.session_id,
        active_search_id=payload.active_search_id,
        ui_state_json=payload.ui_state,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_session_out(session)


@router.post("/close", response_model=SessionOut)
def close(payload: SessionCloseIn, db: Session = Depends(get_db)) -> SessionOut:
    session = close_session(db, session_id=payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _to_session_out(session)


def _validate_search_for_session(db: Session, cv_id: str, active_search_id: str | None) -> None:
    if not active_search_id:
        return
    search = db.get(models.SearchConfig, active_search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found for active_search_id")
    if search.cv_id != cv_id:
        raise HTTPException(status_code=400, detail="active_search_id does not belong to session CV")


def _to_session_out(session: models.CVSession) -> SessionOut:
    return SessionOut(
        session_id=session.id,
        cv_id=session.cv_id,
        cv_filename=session.cv.filename if session.cv else None,
        active_search_id=session.active_search_id,
        ui_state=session.ui_state_json or {},
        status=session.status,
        analysis_executed_at=session.analysis_executed_at,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
    )
