from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.schemas import InsightGenerateIn, InsightOut, InsightPayloadOut
from app.services.insights_service import generate_feedback_insight, get_latest_feedback_insight

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("/cv/{cv_id}/generate", response_model=InsightOut)
def generate_insight(cv_id: str, payload: InsightGenerateIn, db: Session = Depends(get_db)) -> InsightOut:
    if not db.get(models.CVDocument, cv_id):
        raise HTTPException(status_code=404, detail="CV not found")

    try:
        insight = generate_feedback_insight(db, cv_id=cv_id, days=payload.days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _serialize_insight(insight)


@router.get("/cv/{cv_id}/latest", response_model=InsightOut | None)
def get_latest_insight(cv_id: str, db: Session = Depends(get_db)) -> InsightOut | None:
    if not db.get(models.CVDocument, cv_id):
        raise HTTPException(status_code=404, detail="CV not found")

    insight = get_latest_feedback_insight(db, cv_id=cv_id)
    if not insight:
        return None
    return _serialize_insight(insight)


@router.get("/cv/{cv_id}/history", response_model=list[InsightOut])
def get_insight_history(
    cv_id: str,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[InsightOut]:
    if not db.get(models.CVDocument, cv_id):
        raise HTTPException(status_code=404, detail="CV not found")

    rows = db.scalars(
        select(models.Insight)
        .where(models.Insight.cv_id == cv_id)
        .order_by(desc(models.Insight.created_at))
        .limit(limit)
    ).all()
    return [_serialize_insight(item) for item in rows]


def _serialize_insight(item: models.Insight) -> InsightOut:
    payload = item.insights_json or {}
    return InsightOut(
        insight_id=item.id,
        cv_id=item.cv_id,
        period_start=item.period_start,
        period_end=item.period_end,
        created_at=item.created_at,
        model_name=item.model_name,
        token_in=item.token_in or 0,
        token_out=item.token_out or 0,
        insights=InsightPayloadOut(
            fit_outlook=payload.get("fit_outlook") or {},
            search_improvements=payload.get("search_improvements") or {},
            cv_recommendations=payload.get("cv_recommendations") or [],
            weekly_plan=payload.get("weekly_plan") or [],
            llm_status=payload.get("llm_status") or "fallback",
            llm_error=payload.get("llm_error"),
        ),
    )
