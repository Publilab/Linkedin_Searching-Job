from __future__ import annotations

import asyncio
from datetime import datetime
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal, get_db
from app.schemas import (
    CheckUpdateIn,
    SearchConfigOut,
    SearchCreateIn,
    SearchCreateOut,
    SearchFacetsOut,
    SearchSourceOut,
    SearchUpdateIn,
    SearchResultsOut,
    SearchResultOut,
    SearchRunOut,
)
from app.services.job_sources import list_allowed_sources, normalize_sources
from app.services.search_service import run_search_once
from app.services.session_service import update_session_state

router = APIRouter(prefix="/searches", tags=["searches"])


def _serialize_results(
    db: Session,
    search_id: str,
    *,
    only_new: bool = False,
    sort_by: Literal["newest", "best_fit"] = "newest",
    source: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    max_posted_hours: float | None = None,
    location_contains: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> SearchResultsOut:
    stmt = (
        select(models.SearchResult, models.JobPosting, models.ResultCheck)
        .join(models.JobPosting, models.SearchResult.job_posting_id == models.JobPosting.id)
        .outerjoin(models.ResultCheck, models.ResultCheck.search_result_id == models.SearchResult.id)
        .where(models.SearchResult.search_config_id == search_id)
        .where(models.JobPosting.applicant_count < 100)
    )

    if only_new:
        stmt = stmt.where(models.SearchResult.is_new.is_(True))
    if source:
        stmt = stmt.where(models.JobPosting.source == source)
    if category:
        stmt = stmt.where(models.JobPosting.job_category == category)
    if subcategory:
        stmt = stmt.where(models.JobPosting.job_subcategory == subcategory)
    if location_contains:
        stmt = stmt.where(models.JobPosting.location.ilike(f"%{location_contains}%"))

    if sort_by == "best_fit":
        stmt = stmt.order_by(desc(models.SearchResult.final_score), desc(models.SearchResult.discovered_at))
    else:
        stmt = stmt.order_by(desc(models.SearchResult.discovered_at))

    rows = db.execute(stmt).all()

    now = datetime.utcnow()
    items: list[SearchResultOut] = []
    for result, job, check in rows:
        posted_age = _posted_age_hours(job.posted_at, now)
        if max_posted_hours is not None:
            if posted_age is None or posted_age > max_posted_hours:
                continue

        items.append(
            SearchResultOut(
                result_id=result.id,
                job_id=job.id,
                source=job.source,
                title=job.title,
                company=job.company,
                description=job.description,
                location=job.location,
                modality=job.modality,
                easy_apply=job.easy_apply,
                applicant_count=job.applicant_count,
                job_category=job.job_category,
                job_subcategory=job.job_subcategory,
                match_percent=result.match_percent,
                llm_fit_score=_display_llm_fit_score(
                    result.llm_fit_score,
                    match_percent=result.match_percent,
                    llm_status=result.llm_status,
                ),
                final_score=result.final_score,
                match_breakdown=result.match_breakdown_json or {},
                fit_reasons=result.fit_reasons_json or [],
                gap_notes=result.gap_notes_json or [],
                role_alignment=result.role_alignment_json or [],
                llm_status=result.llm_status or "fallback",
                job_url=job.canonical_url,
                posted_at=job.posted_at,
                posted_age_hours=posted_age,
                discovered_at=result.discovered_at,
                is_new=result.is_new,
                checked=bool(check.checked) if check else False,
            )
        )

    total = len(items)
    safe_page = max(1, int(page))
    safe_page_size = max(1, int(page_size))
    total_pages = math.ceil(total / safe_page_size) if total > 0 else 0

    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    paged_items = items[start:end]

    return SearchResultsOut(
        search_id=search_id,
        total=total,
        page=safe_page,
        page_size=safe_page_size,
        total_pages=total_pages,
        has_prev=safe_page > 1,
        has_next=safe_page < total_pages,
        items=paged_items,
    )


@router.get("/sources", response_model=list[SearchSourceOut])
def get_allowed_sources() -> list[SearchSourceOut]:
    return [
        SearchSourceOut(
            source_id=item.source_id,
            label=item.label,
            description=item.description,
            enabled=bool(item.enabled),
            status_note=item.status_note,
        )
        for item in list_allowed_sources()
    ]


@router.post("", response_model=SearchCreateOut)
async def create_search(payload: SearchCreateIn, db: Session = Depends(get_db)) -> SearchCreateOut:
    cv = db.get(models.CVDocument, payload.cv_id)
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == payload.cv_id))
    if not profile:
        raise HTTPException(status_code=400, detail="CV summary must exist before searching")

    sources = normalize_sources(payload.sources)

    search = models.SearchConfig(
        cv_id=payload.cv_id,
        country=payload.country,
        city=payload.city,
        time_window_hours=payload.time_window_hours,
        keywords_json=payload.keywords,
        sources_json=sources,
        active=True,
    )
    db.add(search)
    db.commit()
    db.refresh(search)

    active_session = db.scalar(
        select(models.CVSession)
        .where(models.CVSession.cv_id == payload.cv_id, models.CVSession.status == "active")
        .order_by(desc(models.CVSession.last_seen_at))
    )
    if active_session:
        update_session_state(db, session_id=active_session.id, active_search_id=search.id)

    run_data = await asyncio.to_thread(run_search_once, SessionLocal, search.id, "manual")

    run_out = SearchRunOut(**run_data)
    results_out = _serialize_results(db, search.id)
    return SearchCreateOut(search_id=search.id, run=run_out, results=results_out)


@router.get("/{search_id}", response_model=SearchConfigOut)
def get_search(search_id: str, db: Session = Depends(get_db)) -> SearchConfigOut:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    return _search_config_out(search)


@router.patch("/{search_id}", response_model=SearchConfigOut)
def update_search(
    search_id: str,
    payload: SearchUpdateIn,
    db: Session = Depends(get_db),
) -> SearchConfigOut:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    updates = payload.model_dump(exclude_unset=True)
    if "country" in updates:
        search.country = updates["country"]
    if "city" in updates:
        search.city = updates["city"]
    if "time_window_hours" in updates:
        search.time_window_hours = updates["time_window_hours"]
    if "keywords" in updates:
        search.keywords_json = updates["keywords"] or []
    if "sources" in updates:
        search.sources_json = normalize_sources(updates["sources"] or [])
    if "active" in updates:
        search.active = bool(updates["active"])

    db.add(search)
    db.commit()
    db.refresh(search)
    return _search_config_out(search)


@router.post("/{search_id}/run", response_model=SearchRunOut)
async def run_search(search_id: str, db: Session = Depends(get_db)) -> SearchRunOut:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    run_data = await asyncio.to_thread(run_search_once, SessionLocal, search_id, "manual")
    return SearchRunOut(**run_data)


@router.get("/{search_id}/results", response_model=SearchResultsOut)
def get_results(
    search_id: str,
    only_new: bool = Query(default=False),
    sort_by: Literal["newest", "best_fit"] = Query(default="newest"),
    source: str | None = Query(default=None),
    category: str | None = Query(default=None),
    subcategory: str | None = Query(default=None),
    max_posted_hours: float | None = Query(default=None, ge=0),
    location_contains: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SearchResultsOut:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    return _serialize_results(
        db,
        search_id,
        only_new=only_new,
        sort_by=sort_by,
        source=source,
        category=category,
        subcategory=subcategory,
        max_posted_hours=max_posted_hours,
        location_contains=location_contains,
        page=page,
        page_size=page_size,
    )


@router.delete("/{search_id}/results", response_model=dict)
def clear_results(search_id: str, db: Session = Depends(get_db)) -> dict:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    rows = db.scalars(
        select(models.SearchResult).where(models.SearchResult.search_config_id == search_id)
    ).all()
    deleted = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()

    return {"search_id": search_id, "deleted": deleted}


@router.get("/{search_id}/new-count", response_model=dict)
def get_new_count(search_id: str, db: Session = Depends(get_db)) -> dict:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    count = (
        db.query(models.SearchResult)
        .join(models.JobPosting, models.SearchResult.job_posting_id == models.JobPosting.id)
        .filter(
            models.SearchResult.search_config_id == search_id,
            models.SearchResult.is_new.is_(True),
            models.JobPosting.applicant_count < 100,
        )
        .count()
    )
    return {"search_id": search_id, "new_count": count}


@router.get("/{search_id}/facets", response_model=SearchFacetsOut)
def get_facets(search_id: str, db: Session = Depends(get_db)) -> SearchFacetsOut:
    search = db.get(models.SearchConfig, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    rows = db.execute(
        select(models.SearchResult, models.JobPosting)
        .join(models.JobPosting, models.SearchResult.job_posting_id == models.JobPosting.id)
        .where(models.SearchResult.search_config_id == search_id)
        .where(models.JobPosting.applicant_count < 100)
    ).all()

    now = datetime.utcnow()

    categories: dict[str, int] = {}
    subcategories: dict[str, int] = {}
    modalities: dict[str, int] = {}
    locations: dict[str, int] = {}
    sources: dict[str, int] = {}
    posted_buckets = {"1h": 0, "3h": 0, "8h": 0, "24h": 0, "72h": 0, "168h": 0, "720h": 0, "older": 0, "unknown": 0}

    for _, job in rows:
        _inc(categories, job.job_category or "Uncategorized")
        _inc(subcategories, job.job_subcategory or "Other")
        _inc(modalities, job.modality or "unknown")
        _inc(locations, job.location or "unknown")
        _inc(sources, job.source or "unknown")

        age = _posted_age_hours(job.posted_at, now)
        if age is None:
            posted_buckets["unknown"] += 1
        elif age <= 1:
            posted_buckets["1h"] += 1
        elif age <= 3:
            posted_buckets["3h"] += 1
        elif age <= 8:
            posted_buckets["8h"] += 1
        elif age <= 24:
            posted_buckets["24h"] += 1
        elif age <= 72:
            posted_buckets["72h"] += 1
        elif age <= 168:
            posted_buckets["168h"] += 1
        elif age <= 720:
            posted_buckets["720h"] += 1
        else:
            posted_buckets["older"] += 1

    return SearchFacetsOut(
        categories=categories,
        subcategories=subcategories,
        modalities=modalities,
        locations=locations,
        sources=sources,
        posted_buckets=posted_buckets,
    )


@router.patch("/results/{result_id}/check", response_model=dict)
def set_result_check(result_id: str, payload: CheckUpdateIn, db: Session = Depends(get_db)) -> dict:
    result = db.get(models.SearchResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    check = db.scalar(select(models.ResultCheck).where(models.ResultCheck.search_result_id == result_id))
    if not check:
        check = models.ResultCheck(search_result_id=result_id, checked=payload.checked)
    else:
        check.checked = payload.checked
        check.updated_at = datetime.utcnow()

    result.is_new = False

    db.add(check)
    db.add(result)
    db.commit()

    return {"result_id": result_id, "checked": payload.checked}


def _inc(store: dict[str, int], key: str) -> None:
    store[key] = store.get(key, 0) + 1


def _posted_age_hours(posted_at: datetime | None, now: datetime | None = None) -> float | None:
    if not posted_at:
        return None
    ref = now or datetime.utcnow()
    return round(max((ref - posted_at).total_seconds() / 3600.0, 0.0), 2)


def _display_llm_fit_score(
    llm_fit_score: float | None,
    *,
    match_percent: float | None,
    llm_status: str | None,
) -> float:
    try:
        value = float(llm_fit_score or 0.0)
    except (TypeError, ValueError):
        value = 0.0

    try:
        fallback = float(match_percent or 0.0)
    except (TypeError, ValueError):
        fallback = 0.0

    if value <= 0 and (llm_status or "fallback") == "fallback" and fallback > 0:
        value = fallback
    return round(min(max(value, 0.0), 100.0), 2)


def _search_config_out(search: models.SearchConfig) -> SearchConfigOut:
    return SearchConfigOut(
        search_id=search.id,
        cv_id=search.cv_id,
        country=search.country,
        city=search.city,
        time_window_hours=search.time_window_hours,
        keywords=search.keywords_json or [],
        sources=normalize_sources(search.sources_json or []),
        active=bool(search.active),
    )
