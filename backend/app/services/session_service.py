from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy import delete as sa_delete
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
    rows = db.scalars(select(models.CVSession).order_by(desc(models.CVSession.created_at))).all()
    out: list[models.CVSession] = []
    seen_cv_ids: set[str] = set()
    for session in rows:
        if session.cv_id in seen_cv_ids:
            continue
        seen_cv_ids.add(session.cv_id)
        out.append(session)
        if len(out) >= safe_limit:
            break
    return out


def get_latest_session_for_cv(db: Session, *, cv_id: str) -> models.CVSession | None:
    return db.scalar(
        select(models.CVSession)
        .where(models.CVSession.cv_id == cv_id)
        .order_by(desc(models.CVSession.created_at))
    )


def delete_session_group(db: Session, *, session_id: str) -> bool:
    target = db.get(models.CVSession, session_id)
    if not target:
        return False

    db.execute(sa_delete(models.CVSession).where(models.CVSession.cv_id == target.cv_id))
    db.commit()
    return True



def purge_database_except_active_session(
    db: Session,
    *,
    keep_session_id: str | None = None,
) -> dict[str, int | str | None]:
    keep_session: models.CVSession | None = None
    if keep_session_id:
        keep_session = db.get(models.CVSession, keep_session_id)

    if not keep_session:
        keep_session = db.scalar(
            select(models.CVSession)
            .where(models.CVSession.status == "active")
            .order_by(desc(models.CVSession.last_seen_at))
        )

    if not keep_session:
        keep_session = db.scalar(select(models.CVSession).order_by(desc(models.CVSession.last_seen_at)))

    kept_session_id = keep_session.id if keep_session else None
    kept_cv_id = keep_session.cv_id if keep_session else None
    kept_search_id = keep_session.active_search_id if keep_session else None

    if kept_session_id:
        deleted_sessions = (
            db.execute(sa_delete(models.CVSession).where(models.CVSession.id != kept_session_id)).rowcount or 0
        )
    else:
        deleted_sessions = db.execute(sa_delete(models.CVSession)).rowcount or 0

    if kept_cv_id:
        if kept_search_id:
            deleted_searches_same_cv = (
                db.execute(
                    sa_delete(models.SearchConfig).where(
                        models.SearchConfig.cv_id == kept_cv_id,
                        models.SearchConfig.id != kept_search_id,
                    )
                ).rowcount
                or 0
            )
        else:
            deleted_searches_same_cv = (
                db.execute(
                    sa_delete(models.SearchConfig).where(models.SearchConfig.cv_id == kept_cv_id)
                ).rowcount
                or 0
            )

        deleted_cv_documents = (
            db.execute(sa_delete(models.CVDocument).where(models.CVDocument.id != kept_cv_id)).rowcount
            or 0
        )
        deleted_insights = (
            db.execute(sa_delete(models.Insight).where(models.Insight.cv_id != kept_cv_id)).rowcount
            or 0
        )
        deleted_llm_usage_logs = (
            db.execute(
                sa_delete(models.LLMUsageLog).where(
                    (models.LLMUsageLog.cv_id.is_(None))
                    | (models.LLMUsageLog.cv_id != kept_cv_id)
                )
            ).rowcount
            or 0
        )
    else:
        deleted_searches_same_cv = 0
        deleted_cv_documents = db.execute(sa_delete(models.CVDocument)).rowcount or 0
        deleted_insights = db.execute(sa_delete(models.Insight)).rowcount or 0
        deleted_llm_usage_logs = db.execute(sa_delete(models.LLMUsageLog)).rowcount or 0

    orphan_result_exists = select(models.SearchResult.id).where(
        models.SearchResult.job_posting_id == models.JobPosting.id
    )
    deleted_orphan_jobs = (
        db.execute(sa_delete(models.JobPosting).where(~orphan_result_exists.exists())).rowcount or 0
    )

    db.commit()

    if kept_session_id:
        surviving = db.get(models.CVSession, kept_session_id)
        if surviving:
            _deactivate_active_sessions(db, keep_session_id=surviving.id)
            surviving.status = "active"
            _touch(surviving)
            db.add(surviving)
            db.commit()

    return {
        "kept_session_id": kept_session_id,
        "kept_cv_id": kept_cv_id,
        "kept_search_id": kept_search_id,
        "deleted_sessions": deleted_sessions,
        "deleted_cv_documents": deleted_cv_documents,
        "deleted_searches_same_cv": deleted_searches_same_cv,
        "deleted_orphan_jobs": deleted_orphan_jobs,
        "deleted_insights": deleted_insights,
        "deleted_llm_usage_logs": deleted_llm_usage_logs,
    }


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
