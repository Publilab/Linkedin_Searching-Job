from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.schemas import (
    CVAnalysisOut,
    CVSearchStrategyOut,
    CVSummary,
    CVSummaryOut,
    CVSummaryUpdateIn,
    CVUploadOut,
    MarketRoleOut,
)
from app.services.cv_extract import extract_text_from_upload
from app.services.cv_summary import summarize_cv_text
from app.services.market_demand_service import build_search_strategy
from app.services.profile_ai_service import analyze_profile

router = APIRouter(prefix="/cv", tags=["cv"])


@router.post("/upload", response_model=CVUploadOut)
async def upload_cv(file: UploadFile = File(...), db: Session = Depends(get_db)) -> CVUploadOut:
    filename = file.filename or "cv"
    if not filename.lower().endswith((".pdf", ".docx")):
        raise HTTPException(status_code=400, detail="Only .pdf and .docx are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    file_hash = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(models.CVDocument).where(models.CVDocument.file_hash == file_hash))
    if existing:
        profile = db.scalar(
            select(models.CandidateProfile).where(models.CandidateProfile.cv_id == existing.id)
        )
        summary = (profile.summary_json if profile else {}) or {}
        return CVUploadOut(
            cv_id=existing.id,
            text_chars=len(existing.raw_text),
            summary=CVSummary(**summary),
            analysis=_analysis_out(profile),
            created_at=existing.created_at,
        )

    try:
        raw_text = extract_text_from_upload(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    summary = summarize_cv_text(raw_text)
    ai_bundle = analyze_profile(raw_text, summary)
    summary = ai_bundle["summary"]

    cv = models.CVDocument(filename=filename, file_hash=file_hash, raw_text=raw_text)
    db.add(cv)
    db.flush()

    profile = models.CandidateProfile(
        cv_id=cv.id,
        summary_json=summary,
        skills_json=summary.get("skills", []),
        experience_json=summary.get("experience", []),
        education_json=summary.get("education", []),
        languages_json=summary.get("languages", []),
        llm_profile_json=ai_bundle["llm_profile_json"],
        llm_strategy_json=ai_bundle["llm_strategy_json"],
        profile_fingerprint=ai_bundle["profile_fingerprint"],
        llm_model=ai_bundle["llm_model"],
        llm_prompt_version=ai_bundle["llm_prompt_version"],
        llm_status=ai_bundle["llm_status"],
        llm_error=ai_bundle["llm_error"],
        confirmed_at=None,
    )
    db.add(profile)
    db.commit()
    db.refresh(cv)
    db.refresh(profile)

    return CVUploadOut(
        cv_id=cv.id,
        text_chars=len(raw_text),
        summary=CVSummary(**summary),
        analysis=CVAnalysisOut(**ai_bundle["analysis"], llm_error=ai_bundle.get("llm_error")),
        created_at=cv.created_at,
    )


@router.get("/{cv_id}/summary", response_model=CVSummaryOut)
def get_cv_summary(cv_id: str, db: Session = Depends(get_db)) -> CVSummaryOut:
    cv = db.get(models.CVDocument, cv_id)
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Summary not found")

    return CVSummaryOut(
        cv_id=cv_id,
        summary=CVSummary(**(profile.summary_json or {})),
        analysis=_analysis_out(profile),
        confirmed_at=profile.confirmed_at,
        updated_at=profile.updated_at,
    )


@router.put("/{cv_id}/summary", response_model=CVSummaryOut)
def update_cv_summary(
    cv_id: str,
    payload: CVSummaryUpdateIn,
    db: Session = Depends(get_db),
) -> CVSummaryOut:
    cv = db.get(models.CVDocument, cv_id)
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    if not profile:
        profile = models.CandidateProfile(cv_id=cv_id)

    summary = payload.summary.model_dump()
    ai_bundle = analyze_profile(cv.raw_text, summary)

    profile.summary_json = summary
    profile.skills_json = summary.get("skills", [])
    profile.experience_json = summary.get("experience", [])
    profile.education_json = summary.get("education", [])
    profile.languages_json = summary.get("languages", [])

    profile.llm_profile_json = ai_bundle["llm_profile_json"]
    profile.llm_strategy_json = ai_bundle["llm_strategy_json"]
    profile.profile_fingerprint = ai_bundle["profile_fingerprint"]
    profile.llm_model = ai_bundle["llm_model"]
    profile.llm_prompt_version = ai_bundle["llm_prompt_version"]
    profile.llm_status = ai_bundle["llm_status"]
    profile.llm_error = ai_bundle["llm_error"]

    profile.confirmed_at = datetime.utcnow()

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return CVSummaryOut(
        cv_id=cv_id,
        summary=payload.summary,
        analysis=CVAnalysisOut(**ai_bundle["analysis"], llm_error=ai_bundle.get("llm_error")),
        confirmed_at=profile.confirmed_at,
        updated_at=profile.updated_at,
    )


@router.post("/{cv_id}/analyze", response_model=CVSummaryOut)
def analyze_cv_summary(cv_id: str, db: Session = Depends(get_db)) -> CVSummaryOut:
    cv = db.get(models.CVDocument, cv_id)
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Summary not found")

    summary = profile.summary_json or {}
    ai_bundle = analyze_profile(cv.raw_text, summary)

    profile.llm_profile_json = ai_bundle["llm_profile_json"]
    profile.llm_strategy_json = ai_bundle["llm_strategy_json"]
    profile.profile_fingerprint = ai_bundle["profile_fingerprint"]
    profile.llm_model = ai_bundle["llm_model"]
    profile.llm_prompt_version = ai_bundle["llm_prompt_version"]
    profile.llm_status = ai_bundle["llm_status"]
    profile.llm_error = ai_bundle["llm_error"]

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return CVSummaryOut(
        cv_id=cv_id,
        summary=CVSummary(**summary),
        analysis=CVAnalysisOut(**ai_bundle["analysis"], llm_error=ai_bundle.get("llm_error")),
        confirmed_at=profile.confirmed_at,
        updated_at=profile.updated_at,
    )


@router.get("/{cv_id}/strategy", response_model=CVSearchStrategyOut)
def get_cv_strategy(cv_id: str, db: Session = Depends(get_db)) -> CVSearchStrategyOut:
    cv = db.get(models.CVDocument, cv_id)
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Summary not found")

    summary = profile.summary_json or {}
    analysis = _analysis_out(profile).model_dump()
    strategy = build_search_strategy(summary, analysis)

    return CVSearchStrategyOut(
        cv_id=cv_id,
        role_focus=strategy.get("role_focus", []) or [],
        recommended_queries=strategy.get("recommended_queries", []) or [],
        market_roles=[MarketRoleOut(**item) for item in strategy.get("market_roles", [])],
    )


def _analysis_out(profile: models.CandidateProfile | None) -> CVAnalysisOut:
    if not profile:
        return CVAnalysisOut()

    profile_json = profile.llm_profile_json or {}
    strategy_json = profile.llm_strategy_json or {}
    return CVAnalysisOut(
        target_roles=profile_json.get("target_roles", []) or [],
        secondary_roles=profile_json.get("secondary_roles", []) or [],
        seniority=profile_json.get("seniority", "unknown") or "unknown",
        industries=profile_json.get("industries", []) or [],
        strengths=profile_json.get("strengths", []) or [],
        skill_gaps=profile_json.get("skill_gaps", []) or [],
        recommended_queries=strategy_json.get("recommended_queries", []) or [],
        llm_status=profile.llm_status or "fallback",
        llm_error=profile.llm_error,
    )
