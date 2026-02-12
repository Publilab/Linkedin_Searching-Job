from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from app import models
from app.services.learning_service import summarize_preference_strengths
from app.services.llm import LLMClientError, get_llm_client
from app.services.llm.prompts import build_feedback_insights_prompt
from app.services.llm.schemas import LLMFeedbackInsights
from app.services.market_demand_service import build_search_strategy
from app.services.runtime_settings import load_runtime_llm_config


EVENT_IMPORTANCE = {
    "open": 1.0,
    "save": 2.0,
    "apply": 3.0,
    "dismiss": -1.0,
    "check": 0.5,
    "uncheck": -0.5,
}


def generate_feedback_insight(db: Session, *, cv_id: str, days: int = 7) -> models.Insight:
    cv = db.get(models.CVDocument, cv_id)
    if cv is None:
        raise ValueError("CV not found")

    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=max(int(days), 1))
    digest = build_feedback_digest(db, cv_id=cv_id, period_start=period_start, period_end=period_end)

    payload: dict[str, Any]
    model_name: str | None = None
    token_in = 0
    token_out = 0

    runtime_cfg = load_runtime_llm_config(db)
    client = get_llm_client()
    if client.enabled:
        prompt = build_feedback_insights_prompt(prompt_version=runtime_cfg.prompt_version, digest=digest)
        try:
            parsed = LLMFeedbackInsights.model_validate(client.generate_json(prompt))
            payload = {
                "fit_outlook": parsed.fit_outlook.model_dump(),
                "search_improvements": parsed.search_improvements.model_dump(),
                "cv_recommendations": [item.model_dump() for item in parsed.cv_recommendations],
                "weekly_plan": [item.model_dump() for item in parsed.weekly_plan],
                "llm_status": "ok",
                "llm_error": None,
            }
            model_name = runtime_cfg.model
        except (LLMClientError, ValueError) as exc:
            payload = _fallback_insight_payload(digest, error=str(exc))
    else:
        payload = _fallback_insight_payload(
            digest,
            error=f"LLM disabled or missing {runtime_cfg.provider} configuration",
        )

    insight = models.Insight(
        cv_id=cv_id,
        period_start=period_start,
        period_end=period_end,
        insights_json=payload,
        model_name=model_name,
        token_in=token_in,
        token_out=token_out,
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


def get_latest_feedback_insight(db: Session, *, cv_id: str) -> models.Insight | None:
    return db.scalar(
        select(models.Insight)
        .where(models.Insight.cv_id == cv_id)
        .order_by(desc(models.Insight.created_at))
    )


def build_feedback_digest(
    db: Session,
    *,
    cv_id: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    summary = (profile.summary_json if profile else {}) or {}
    profile_analysis = {
        "target_roles": ((profile.llm_profile_json or {}).get("target_roles", []) if profile else []) or [],
        "secondary_roles": ((profile.llm_profile_json or {}).get("secondary_roles", []) if profile else []) or [],
        "seniority": ((profile.llm_profile_json or {}).get("seniority", "unknown") if profile else "unknown")
        or "unknown",
        "industries": ((profile.llm_profile_json or {}).get("industries", []) if profile else []) or [],
        "strengths": ((profile.llm_profile_json or {}).get("strengths", []) if profile else []) or [],
        "skill_gaps": ((profile.llm_profile_json or {}).get("skill_gaps", []) if profile else []) or [],
        "recommended_queries": ((profile.llm_strategy_json or {}).get("recommended_queries", []) if profile else []) or [],
        "llm_status": (profile.llm_status if profile else "fallback") or "fallback",
    }

    strategy = build_search_strategy(summary, profile_analysis)

    interactions_rows = db.execute(
        select(models.Interaction, models.JobPosting)
        .outerjoin(models.JobPosting, models.Interaction.job_posting_id == models.JobPosting.id)
        .where(
            and_(
                models.Interaction.cv_id == cv_id,
                models.Interaction.ts >= period_start,
                models.Interaction.ts <= period_end,
            )
        )
        .order_by(desc(models.Interaction.ts))
        .limit(1000)
    ).all()

    event_counts: Counter[str] = Counter()
    job_scores: dict[str, dict[str, Any]] = {}
    for interaction, job in interactions_rows:
        event_type = str(interaction.event_type or "open").lower()
        event_counts[event_type] += 1

        if not job:
            continue
        key = job.id
        if key not in job_scores:
            job_scores[key] = {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "category": job.job_category,
                "score": 0.0,
            }
        job_scores[key]["score"] += EVENT_IMPORTANCE.get(event_type, 0.0)

    top_jobs = sorted(job_scores.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)[:10]

    search_rows = db.scalars(
        select(models.SearchConfig)
        .where(models.SearchConfig.cv_id == cv_id)
        .order_by(desc(models.SearchConfig.created_at))
        .limit(8)
    ).all()
    search_ids = [row.id for row in search_rows]

    run_rows = []
    if search_ids:
        run_rows = db.scalars(
            select(models.SchedulerRun)
            .where(
                and_(
                    models.SchedulerRun.search_config_id.in_(search_ids),
                    models.SchedulerRun.started_at >= period_start,
                )
            )
            .order_by(desc(models.SchedulerRun.started_at))
            .limit(60)
        ).all()

    result_rows = []
    if search_ids:
        result_rows = db.execute(
            select(models.SearchResult, models.JobPosting)
            .join(models.JobPosting, models.SearchResult.job_posting_id == models.JobPosting.id)
            .where(models.SearchResult.search_config_id.in_(search_ids))
            .order_by(desc(models.SearchResult.discovered_at))
            .limit(300)
        ).all()

    total_results = len(result_rows)
    easy_apply_count = sum(1 for _, job in result_rows if bool(job.easy_apply))
    avg_final_score = round(
        sum(float(result.final_score or 0.0) for result, _ in result_rows) / max(total_results, 1),
        2,
    )

    recent_queries: list[str] = []
    for search in search_rows:
        for keyword in search.keywords_json or []:
            if isinstance(keyword, str):
                cleaned = " ".join(keyword.split())
                if cleaned and cleaned.lower() not in {q.lower() for q in recent_queries}:
                    recent_queries.append(cleaned)

    learned_preferences = summarize_preference_strengths((profile.learned_preferences_json if profile else {}) or {})

    return {
        "cv_id": cv_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "profile": {
            "summary": summary,
            "analysis": profile_analysis,
            "learned_preferences": learned_preferences,
        },
        "searches": {
            "count": len(search_rows),
            "recent_queries": recent_queries[:20],
            "strategy_queries": strategy.get("recommended_queries", [])[:20],
            "sources": [search.sources_json or [] for search in search_rows[:3]],
            "windows_hours": [search.time_window_hours for search in search_rows[:3]],
        },
        "runs": {
            "count": len(run_rows),
            "total_found": sum(int(run.total_found or 0) for run in run_rows),
            "new_found": sum(int(run.new_found or 0) for run in run_rows),
        },
        "results_stats": {
            "total_results": total_results,
            "avg_final_score": avg_final_score,
            "easy_apply_ratio": round(easy_apply_count / max(total_results, 1), 3),
        },
        "interaction_stats": {
            "total": len(interactions_rows),
            "events": dict(event_counts),
        },
        "top_jobs": top_jobs,
    }


def _fallback_insight_payload(digest: dict[str, Any], *, error: str | None) -> dict[str, Any]:
    profile = digest.get("profile", {}) if isinstance(digest, dict) else {}
    summary = profile.get("summary", {}) if isinstance(profile.get("summary"), dict) else {}
    analysis = profile.get("analysis", {}) if isinstance(profile.get("analysis"), dict) else {}

    target_roles = []
    for role in list(analysis.get("target_roles") or [])[:6]:
        target_roles.append(
            {
                "role": role,
                "probability": 0.7,
                "why": ["Role inferred from CV and previous interactions"],
            }
        )

    strengths = list(analysis.get("strengths") or [])[:8]
    gaps = []
    for gap in list(analysis.get("skill_gaps") or [])[:6]:
        gaps.append({"gap": gap, "impact": "medium", "fix": ["Add this skill to active queries and CV highlights"]})

    add_queries = list((digest.get("searches") or {}).get("strategy_queries") or [])[:10]
    if not add_queries:
        add_queries = list((analysis.get("recommended_queries") or [])[:10])

    recent_queries = list((digest.get("searches") or {}).get("recent_queries") or [])
    remove_queries = [q for q in recent_queries if len(q.split()) <= 1][:5]

    top_locations = list((profile.get("learned_preferences") or {}).get("top_locations") or [])
    locations = [item.get("label") for item in top_locations if isinstance(item, dict) and item.get("label")][:3]

    cv_recommendations = []
    for skill in list(summary.get("skills") or [])[:3]:
        cv_recommendations.append(
            {
                "change": f"Highlight measurable impact for {skill}",
                "reason": "Improves relevance signals in rankers and recruiter scans",
                "example_text": f"Applied {skill} to improve process KPIs by X% in latest role.",
            }
        )

    weekly_plan = [
        {"day": "Mon", "actions": ["Revisar top 20 resultados y marcar ofertas relevantes", "Actualizar consultas activas"]},
        {"day": "Wed", "actions": ["Ejecutar nueva búsqueda y comparar cambios de score", "Ajustar filtros de ubicación/tiempo"]},
        {"day": "Fri", "actions": ["Priorizar ofertas con mayor final_score y menor applicant_count"]},
    ]

    return {
        "fit_outlook": {
            "target_roles": target_roles,
            "strengths": strengths,
            "gaps": gaps,
        },
        "search_improvements": {
            "add_queries": add_queries,
            "remove_queries": remove_queries,
            "recommended_filters": {
                "date_posted": "24h",
                "location": locations,
                "modalities": ["remote", "hybrid"],
                "source_bias": ["linkedin_public", "empleos_publicos_public", "bne_public"],
            },
            "rerank_rules": [
                {"rule": "prefer_recent_low_applicants", "weight": 0.25},
                {"rule": "boost_roles_from_positive_interactions", "weight": 0.35},
            ],
        },
        "cv_recommendations": cv_recommendations,
        "weekly_plan": weekly_plan,
        "llm_status": "fallback",
        "llm_error": error,
    }
