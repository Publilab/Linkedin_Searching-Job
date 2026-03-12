from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.schemas import InteractionCreateIn, InteractionOut
from app.services.learning_service import update_preferences_from_interaction

router = APIRouter(prefix="/interactions", tags=["interactions"])


@router.post("", response_model=InteractionOut)
def create_interaction(payload: InteractionCreateIn, db: Session = Depends(get_db)) -> InteractionOut:
    search: models.SearchConfig | None = None
    job: models.JobPosting | None = None
    session: models.CVSession | None = None

    if payload.session_id:
        session = db.get(models.CVSession, payload.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    if payload.result_id:
        result = db.get(models.SearchResult, payload.result_id)
        if not result:
            raise HTTPException(status_code=404, detail="Result not found")
        search = db.get(models.SearchConfig, result.search_config_id)
        job = db.get(models.JobPosting, result.job_posting_id)

    if payload.search_id and search is None:
        search = db.get(models.SearchConfig, payload.search_id)
        if not search:
            raise HTTPException(status_code=404, detail="Search not found")

    if payload.job_id and job is None:
        job = db.get(models.JobPosting, payload.job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

    cv_id = payload.cv_id
    if not cv_id and search:
        cv_id = search.cv_id
    if not cv_id and session:
        cv_id = session.cv_id
    if not cv_id:
        raise HTTPException(status_code=400, detail="cv_id or derivable context is required")

    if not db.get(models.CVDocument, cv_id):
        raise HTTPException(status_code=404, detail="CV not found")

    interaction = models.Interaction(
        cv_id=cv_id,
        session_id=(session.id if session else payload.session_id),
        search_config_id=(search.id if search else payload.search_id),
        job_posting_id=(job.id if job else payload.job_id),
        event_type=payload.event_type,
        dwell_ms=payload.dwell_ms,
        meta_json=payload.meta or {},
        ts=datetime.utcnow(),
    )
    db.add(interaction)

    update_preferences_from_interaction(
        db,
        cv_id=cv_id,
        event_type=payload.event_type,
        job=job,
        dwell_ms=payload.dwell_ms,
        meta=payload.meta or {},
    )

    db.commit()
    db.refresh(interaction)

    return InteractionOut(
        interaction_id=interaction.id,
        cv_id=interaction.cv_id,
        session_id=interaction.session_id,
        search_id=interaction.search_config_id,
        job_id=interaction.job_posting_id,
        event_type=interaction.event_type,
        dwell_ms=interaction.dwell_ms,
        ts=interaction.ts,
        meta=interaction.meta_json or {},
    )
