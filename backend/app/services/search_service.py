from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.services.job_ai_service import compute_job_content_hash, evaluate_job_fit
from app.services.job_sources import fetch_jobs, normalize_sources
from app.services.linkedin_scraper import scrape_jobs as scrape_linkedin_jobs
from app.services.learning_service import personalization_score_for_job, preferred_query_seeds
from app.services.matcher import compute_match
from app.services.runtime_settings import load_runtime_llm_config

# Backward-compatible alias used by tests that monkeypatch this symbol.
scrape_jobs = scrape_linkedin_jobs

_NOISE_QUERY_TOKENS = {
    "sector publico",
    "sector público",
    "public sector",
    "sector privado",
    "private sector",
    "government sector",
}

_ROLE_QUERY_EXPANSIONS: dict[str, list[str]] = {
    "analista de datos": ["data analyst", "business intelligence analyst"],
    "data analyst": ["analista de datos", "business intelligence analyst"],
    "cientifico de datos": ["data scientist", "machine learning analyst"],
    "data scientist": ["cientifico de datos", "machine learning engineer"],
    "gerente de proyectos": ["project manager", "pmo manager"],
    "project manager": ["gerente de proyectos", "pmo manager"],
    "jefe de recursos humanos": ["human resources manager", "people operations manager"],
    "analista de recursos humanos": ["human resources analyst", "people operations analyst"],
    "human resources analyst": ["analista de recursos humanos", "people operations analyst"],
    "people operations": ["recursos humanos", "human resources"],
    "administrador publico": ["public administrator", "public administration"],
    "administrador público": ["public administrator", "public administration"],
    "politicas publicas": ["public policy", "public policy analyst"],
    "políticas públicas": ["public policy", "public policy analyst"],
    "consultor en politicas publicas": ["public policy consultant", "government affairs consultant"],
    "consultor en políticas públicas": ["public policy consultant", "government affairs consultant"],
    "docente universitario": ["university lecturer", "academic coordinator"],
    "academico": ["academic coordinator", "university lecturer"],
    "académico": ["academic coordinator", "university lecturer"],
}


def ensure_scheduler_state(db: Session, interval_minutes: int = 60) -> models.SchedulerState:
    state = db.get(models.SchedulerState, 1)
    if state:
        return state
    state = models.SchedulerState(id=1, is_running=False, interval_minutes=interval_minutes)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def set_scheduler_running(db: Session, *, running: bool, interval_minutes: int | None = None) -> models.SchedulerState:
    state = ensure_scheduler_state(db)
    state.is_running = running
    if interval_minutes is not None:
        state.interval_minutes = interval_minutes
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def scheduler_status(db: Session) -> models.SchedulerState:
    return ensure_scheduler_state(db)


def run_search_once(session_factory: sessionmaker, search_id: str, run_type: str = "manual") -> dict:
    with session_factory() as db:
        search = db.get(models.SearchConfig, search_id)
        if not search:
            raise ValueError("search not found")

        profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == search.cv_id))
        if not profile:
            raise ValueError("profile not found for cv")

        profile_summary = _profile_summary(profile)
        profile_analysis = _profile_analysis(profile)
        learned_preferences = profile.learned_preferences_json or {}
        runtime_cfg = load_runtime_llm_config(db)

        run = models.SchedulerRun(
            search_config_id=search.id,
            run_type=run_type,
            started_at=datetime.utcnow(),
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        search_id_local = search.id
        search_city = search.city
        search_country = search.country
        effective_time_window_hours = 1 if run_type == "scheduled" else search.time_window_hours
        search_sources = normalize_sources(search.sources_json or [])
        if search.sources_json != search_sources:
            search.sources_json = search_sources
            db.add(search)
            db.commit()
        run_id = run.id
        run_started_at = run.started_at

        existing_results = db.scalars(
            select(models.SearchResult).where(models.SearchResult.search_config_id == search_id_local)
        ).all()
        for result in existing_results:
            result.is_new = False
            db.add(result)
        db.commit()

        location_parts = [p for p in [search_city, search_country] if p]
        location = ", ".join(location_parts) if location_parts else ""

        queries = _build_queries(
            profile_summary,
            profile_analysis,
            profile.llm_strategy_json or {},
            search.keywords_json or [],
            learned_preferences=learned_preferences,
        )
        scraped_jobs: dict[str, dict] = {}
        for query in queries:
            for source_id in search_sources:
                if source_id == "linkedin_public":
                    jobs = scrape_jobs(
                        keywords=query,
                        location=location,
                        time_window_hours=effective_time_window_hours,
                        max_results=30,
                    )
                else:
                    jobs = fetch_jobs(
                        source_id=source_id,
                        keywords=query,
                        location=location,
                        city=search_city,
                        country=search_country,
                        time_window_hours=effective_time_window_hours,
                        max_results=30,
                    )

                for job in jobs:
                    key = _dedupe_key(job)
                    if not key:
                        continue
                    existing = scraped_jobs.get(key)
                    if not existing:
                        scraped_jobs[key] = job
                        continue

                    if int(existing.get("applicant_count") or 0) == 0 and int(job.get("applicant_count") or 0) > 0:
                        scraped_jobs[key] = job
                        continue
                    if len((job.get("description") or "")) > len((existing.get("description") or "")):
                        scraped_jobs[key] = job

        new_found = 0
        applicant_limit = _coerce_applicant_limit(search.max_applicant_count)
        llm_budget = max(int(runtime_cfg.max_jobs_per_run), 0)
        candidates: list[dict] = []

        for job in scraped_jobs.values():
            posting = _upsert_posting(db, job)
            if _is_over_applicant_limit(posting.applicant_count, applicant_limit):
                db.commit()
                continue

            score, breakdown = compute_match(profile_summary, job)
            result = db.scalar(
                select(models.SearchResult).where(
                    models.SearchResult.search_config_id == search_id_local,
                    models.SearchResult.job_posting_id == posting.id,
                )
            )
            recency_score = _recency_score(posting.posted_at)
            location_score = _location_score(posting.location, posting.modality, search_city, search_country)
            personalization_score = personalization_score_for_job(posting, learned_preferences)

            candidates.append(
                {
                    "job": job,
                    "posting_id": posting.id,
                    "score": score,
                    "breakdown": breakdown,
                    "result": result,
                    "recency_score": recency_score,
                    "location_score": location_score,
                    "personalization_score": personalization_score,
                    "pre_rank_score": _pre_llm_rank_score(
                        deterministic_score=score,
                        recency_score=recency_score,
                        location_score=location_score,
                        personalization_score=personalization_score,
                    ),
                }
            )
            db.commit()

        candidates.sort(
            key=lambda item: (
                float(item["pre_rank_score"]),
                float(item["personalization_score"]),
                float(item["score"]),
            ),
            reverse=True,
        )
        eligible_found = len(candidates)

        llm_targets = {
            item["posting_id"]
            for item in candidates
            if _needs_llm_refresh(item["result"], db.get(models.JobPosting, item["posting_id"]))
        }
        llm_targets = {
            item["posting_id"]
            for item in candidates
            if item["posting_id"] in llm_targets
        }
        llm_target_ids = []
        for item in candidates:
            posting_id = item["posting_id"]
            if posting_id not in llm_targets:
                continue
            llm_target_ids.append(posting_id)
            if len(llm_target_ids) >= llm_budget:
                break
        llm_target_set = set(llm_target_ids)

        for item in candidates:
            posting_id = item["posting_id"]
            posting = db.get(models.JobPosting, posting_id)
            if posting is None:
                posting = _upsert_posting(db, item["job"])
                posting_id = posting.id

            job_payload = _job_payload(posting)
            result = db.scalar(
                select(models.SearchResult).where(
                    models.SearchResult.search_config_id == search_id_local,
                    models.SearchResult.job_posting_id == posting_id,
                )
            )

            cached_ai = _cached_ai_payload(posting, result, runtime_cfg.prompt_version)

            db.commit()

            if posting_id in llm_target_set:
                ai = evaluate_job_fit(
                    profile_summary,
                    profile_analysis,
                    job_payload,
                    item["score"],
                    allow_llm=True,
                )
            elif cached_ai:
                ai = cached_ai
            else:
                ai = evaluate_job_fit(
                    profile_summary,
                    profile_analysis,
                    job_payload,
                    item["score"],
                    allow_llm=False,
                )

            llm_fit_score = _resolve_llm_fit_score(
                ai.get("llm_fit_score"),
                fallback_score=item["score"],
                llm_status=ai.get("llm_status"),
            )

            posting = db.get(models.JobPosting, posting_id)
            if posting is None:
                posting = _upsert_posting(db, item["job"])
                posting_id = posting.id

            result = db.scalar(
                select(models.SearchResult).where(
                    models.SearchResult.search_config_id == search_id_local,
                    models.SearchResult.job_posting_id == posting_id,
                )
            )

            if ai.get("job_category"):
                posting.job_category = ai.get("job_category")
            if ai.get("job_subcategory"):
                posting.job_subcategory = ai.get("job_subcategory")
            db.add(posting)

            final_score = _final_score(
                deterministic_score=item["score"],
                llm_score=llm_fit_score,
                recency_score=item["recency_score"],
                location_score=item["location_score"],
                personalization_score=item["personalization_score"],
                llm_status=str(ai.get("llm_status") or "fallback"),
                time_window_hours=search.time_window_hours,
            )
            breakdown_with_learning = {
                **(item["breakdown"] or {}),
                "personalization": item["personalization_score"],
                "pre_rank_score": item["pre_rank_score"],
            }

            if result:
                result.match_percent = item["score"]
                result.match_breakdown_json = breakdown_with_learning
                result.llm_fit_score = llm_fit_score
                result.final_score = final_score
                result.fit_reasons_json = ai.get("fit_reasons") or []
                result.gap_notes_json = ai.get("gap_notes") or []
                result.role_alignment_json = ai.get("role_alignment") or []
                result.llm_status = ai.get("llm_status") or "fallback"
                result.llm_analysis_hash = ai.get("llm_analysis_hash") or posting.job_content_hash
                result.is_new = False
                db.add(result)
            else:
                result = models.SearchResult(
                    search_config_id=search_id_local,
                    job_posting_id=posting_id,
                    match_percent=item["score"],
                    match_breakdown_json=breakdown_with_learning,
                    llm_fit_score=llm_fit_score,
                    final_score=final_score,
                    fit_reasons_json=ai.get("fit_reasons") or [],
                    gap_notes_json=ai.get("gap_notes") or [],
                    role_alignment_json=ai.get("role_alignment") or [],
                    llm_status=ai.get("llm_status") or "fallback",
                    llm_analysis_hash=ai.get("llm_analysis_hash") or posting.job_content_hash,
                    is_new=True,
                )
                db.add(result)
                db.flush()
                db.add(models.ResultCheck(search_result_id=result.id, checked=False))
                new_found += 1

            db.commit()

        run = db.get(models.SchedulerRun, run_id)
        if run is None:
            raise RuntimeError("search run not found while finalizing")

        run.total_found = eligible_found
        run.new_found = new_found
        run.status = "ok"
        run.finished_at = datetime.utcnow()
        db.add(run)
        db.commit()

        return {
            "run_id": run.id,
            "search_id": search_id_local,
            "status": run.status,
            "total_found": run.total_found,
            "new_found": run.new_found,
            "started_at": run_started_at,
            "finished_at": run.finished_at,
        }


def run_all_active_searches(session_factory: sessionmaker) -> list[dict]:
    out: list[dict] = []
    with session_factory() as db:
        active_search_ids = [
            row[0]
            for row in db.execute(
                select(models.SearchConfig.id).where(models.SearchConfig.active.is_(True))
            ).all()
        ]

    for search_id in active_search_ids:
        try:
            out.append(run_search_once(session_factory, search_id, run_type="scheduled"))
        except Exception:
            continue

    return out


def _profile_summary(profile: models.CandidateProfile) -> dict:
    summary = profile.summary_json or {
        "skills": profile.skills_json or [],
        "experience": profile.experience_json or [],
        "education": profile.education_json or [],
        "languages": profile.languages_json or [],
        "highlights": [],
    }
    return {
        "skills": summary.get("skills", []) or [],
        "experience": summary.get("experience", []) or [],
        "education": summary.get("education", []) or [],
        "languages": summary.get("languages", []) or [],
        "highlights": summary.get("highlights", []) or [],
    }


def _profile_analysis(profile: models.CandidateProfile) -> dict:
    llm_profile = profile.llm_profile_json or {}
    llm_strategy = profile.llm_strategy_json or {}
    return {
        "target_roles": llm_profile.get("target_roles", []) or [],
        "secondary_roles": llm_profile.get("secondary_roles", []) or [],
        "seniority": llm_profile.get("seniority", "unknown") or "unknown",
        "industries": llm_profile.get("industries", []) or [],
        "strengths": llm_profile.get("strengths", []) or [],
        "skill_gaps": llm_profile.get("skill_gaps", []) or [],
        "recommended_queries": llm_strategy.get("recommended_queries", []) or [],
        "llm_status": profile.llm_status or "fallback",
    }


def _build_queries(
    profile_summary: dict,
    profile_analysis: dict,
    llm_strategy: dict,
    extra_keywords: list[str],
    *,
    learned_preferences: dict | None = None,
) -> list[str]:
    strategy_queries = llm_strategy.get("recommended_queries", []) if isinstance(llm_strategy, dict) else []
    target_roles = profile_analysis.get("target_roles", []) if isinstance(profile_analysis, dict) else []
    secondary_roles = profile_analysis.get("secondary_roles", []) if isinstance(profile_analysis, dict) else []
    strengths = profile_analysis.get("strengths", []) if isinstance(profile_analysis, dict) else []
    industries = profile_analysis.get("industries", []) if isinstance(profile_analysis, dict) else []
    experience = profile_summary.get("experience", []) or []
    skills = profile_summary.get("skills", []) or []
    education = profile_summary.get("education", []) or []

    role_phrases = _extract_role_phrases(list(target_roles) + list(secondary_roles) + experience + education)
    learned_queries = preferred_query_seeds(learned_preferences, limit=8)
    functional_areas = _functional_area_queries(
        skills=skills,
        strengths=strengths,
        industries=industries,
        education=education,
        extra_keywords=extra_keywords,
    )

    seeds: list[str] = []
    seeds.extend([s for s in target_roles[:10] if isinstance(s, str)])
    seeds.extend([s for s in secondary_roles[:8] if isinstance(s, str)])
    seeds.extend([s for s in strategy_queries[:12] if isinstance(s, str)])
    seeds.extend([s for s in learned_queries if isinstance(s, str)])
    seeds.extend(role_phrases[:10])
    seeds.extend(functional_areas[:10])
    seeds.extend([s for s in extra_keywords[:10] if isinstance(s, str)])
    seeds.extend([s for s in skills[:8] if isinstance(s, str)])

    expanded: list[str] = []
    for value in seeds:
        cleaned = _normalize_query_seed(value)
        if not cleaned:
            continue
        expanded.extend(_expand_query_variants(cleaned))

    deduped = _dedupe_queries(expanded)

    if not deduped:
        deduped.append("software engineer")

    return deduped[:20]


def _functional_area_queries(
    *,
    skills: list[str],
    strengths: list[str],
    industries: list[str],
    education: list[str],
    extra_keywords: list[str],
) -> list[str]:
    corpus = " ".join(
        [
            *[value for value in skills if isinstance(value, str)],
            *[value for value in strengths if isinstance(value, str)],
            *[value for value in industries if isinstance(value, str)],
            *[value for value in education if isinstance(value, str)],
            *[value for value in extra_keywords if isinstance(value, str)],
        ]
    ).lower()

    out: list[str] = []
    if _contains_any(corpus, {"python", "sql", "tableau", "power bi", "analytics", "data"}):
        out.extend(["Analista de Datos", "Data Analyst", "Business Intelligence"])
    if _contains_any(
        corpus,
        {
            "rrhh",
            "recursos humanos",
            "human resources",
            "talento humano",
            "people operations",
            "reclutamiento",
            "seleccion",
        },
    ):
        out.extend(["Recursos Humanos", "Human Resources", "People Operations"])
    if _contains_any(
        corpus,
        {
            "administrador publico",
            "administrador público",
            "politicas publicas",
            "políticas públicas",
            "gestion publica",
            "gobierno",
            "municipal",
        },
    ):
        out.extend(["Gestion Publica", "Public Administration", "Public Policy"])
    if _contains_any(corpus, {"project", "proyecto", "pmo", "scrum", "agile", "innovation", "innovacion"}):
        out.extend(["Gerente de Proyectos", "Project Manager", "PMO"])
    if _contains_any(
        corpus,
        {"docencia", "docente", "profesor", "profesora", "academico", "académico", "lecturer", "teaching"},
    ):
        out.extend(["Docente Universitario", "University Lecturer", "Academic Coordinator"])

    return _dedupe_queries(out)


def _extract_role_phrases(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not isinstance(line, str):
            continue
        cleaned = " ".join(line.split())
        low = cleaned.lower()
        if not cleaned:
            continue

        if len(cleaned) > 100:
            continue
        if "•" in cleaned:
            continue
        if re.search(r"\b(universidad|university|instituto|consulting)\b", low):
            continue

        # Remove date suffixes and keep the role/profession part.
        base = re.split(r"\b(19|20)\d{2}\b", cleaned, maxsplit=1)[0].strip(" -|,;")
        if 3 <= len(base) <= 90:
            out.append(base)

        # Common separators in job lines.
        for sep in [" at ", " en ", " - ", " | "]:
            if sep in low:
                part = cleaned[: low.index(sep)].strip(" -|,;")
                if 3 <= len(part) <= 90:
                    out.append(part)
                break

        if any(
            token in low
            for token in [
                "rrhh",
                "recursos humanos",
                "human resources",
                "talento humano",
                "gestion de personas",
                "reclutamiento",
                "seleccion",
            ]
        ):
            out.extend(
                [
                    "Recursos Humanos",
                    "Analista de Recursos Humanos",
                    "Generalista de Recursos Humanos",
                ]
            )

        if any(
            token in low
            for token in [
                "academico",
                "academica",
                "docente",
                "profesor",
                "profesora",
                "instructor",
                "relator",
            ]
        ):
            out.extend(
                [
                    "Academico",
                    "Docente Universitario",
                    "Profesor",
                ]
            )

    return _dedupe_queries(out)


def _dedupe_queries(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_query_seed(value: str) -> str:
    cleaned = " ".join(str(value or "").split()).strip(" -|,;")
    if not cleaned:
        return ""
    cleaned = re.sub(r"\b(19|20)\d{2}\b", "", cleaned).strip(" -|,;")
    cleaned = _strip_sector_terms(cleaned)
    if not cleaned:
        return ""
    if len(cleaned) > 90:
        return ""
    if re.search(r"\b(universidad|university|instituto|consulting)\b", cleaned.lower()):
        return ""
    if cleaned.lower() in _NOISE_QUERY_TOKENS:
        return ""
    return cleaned


def _expand_query_variants(value: str) -> list[str]:
    key = value.lower()
    out = [value]
    if key in _ROLE_QUERY_EXPANSIONS:
        out.extend(_ROLE_QUERY_EXPANSIONS[key])
    return _dedupe_queries([_normalize_query_seed(item) for item in out if _normalize_query_seed(item)])


def _strip_sector_terms(value: str) -> str:
    cleaned = value
    for pattern in [
        r"\bsector publico\b",
        r"\bsector público\b",
        r"\bpublic sector\b",
        r"\bsector privado\b",
        r"\bprivate sector\b",
    ]:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -|,;")


def _contains_any(corpus: str, tokens: set[str]) -> bool:
    low = corpus.lower()
    return any(token in low for token in tokens)


def _dedupe_key(job: dict) -> str | None:
    source = (job.get("source") or "linkedin_public").strip() or "linkedin_public"
    external_id = (job.get("external_job_id") or "").strip()
    if external_id:
        return f"{source}::id::{external_id}"

    url_hash = (job.get("canonical_url_hash") or "").strip()
    if url_hash:
        return f"{source}::url::{url_hash}"

    return None


def _upsert_posting(db: Session, job: dict) -> models.JobPosting:
    source = (job.get("source") or "linkedin_public").strip() or "linkedin_public"
    external_job_id = (job.get("external_job_id") or "").strip() or None
    canonical_hash = (job.get("canonical_url_hash") or "").strip()

    posting = None
    if external_job_id:
        posting = db.scalar(
            select(models.JobPosting).where(
                and_(
                    models.JobPosting.source == source,
                    models.JobPosting.external_job_id == external_job_id,
                )
            )
        )

    if not posting and canonical_hash:
        posting = db.scalar(
            select(models.JobPosting).where(models.JobPosting.canonical_url_hash == canonical_hash)
        )

    now = datetime.utcnow()

    incoming_payload = {
        "title": job.get("title") or (posting.title if posting else "Untitled role"),
        "company": job.get("company") if job.get("company") is not None else (posting.company if posting else None),
        "location": job.get("location") if job.get("location") is not None else (posting.location if posting else None),
        "description": job.get("description") or (posting.description if posting else ""),
        "modality": job.get("modality") if job.get("modality") is not None else (posting.modality if posting else None),
    }
    content_hash = compute_job_content_hash(incoming_payload)

    if posting:
        posting.source = source
        posting.external_job_id = external_job_id
        posting.canonical_url = job.get("canonical_url") or posting.canonical_url

        if canonical_hash and canonical_hash != posting.canonical_url_hash:
            conflict = db.scalar(
                select(models.JobPosting).where(
                    and_(
                        models.JobPosting.canonical_url_hash == canonical_hash,
                        models.JobPosting.id != posting.id,
                    )
                )
            )
            if not conflict:
                posting.canonical_url_hash = canonical_hash

        posting.title = incoming_payload["title"] or posting.title
        posting.company = incoming_payload["company"]
        posting.location = incoming_payload["location"]
        posting.description = incoming_payload["description"] or posting.description
        posting.modality = incoming_payload["modality"]
        posting.easy_apply = bool(job.get("easy_apply", False))
        posting.applicant_count = int(job.get("applicant_count") or 0)
        posting.applicant_count_raw = job.get("applicant_count_raw")
        posting.posted_at = job.get("posted_at")
        posting.job_content_hash = content_hash
        posting.last_seen_at = now
        db.add(posting)
        db.flush()
        return posting

    posting = models.JobPosting(
        source=source,
        external_job_id=external_job_id,
        canonical_url=job.get("canonical_url") or "",
        canonical_url_hash=canonical_hash,
        title=incoming_payload["title"] or "Untitled role",
        company=incoming_payload["company"],
        location=incoming_payload["location"],
        description=incoming_payload["description"] or "",
        modality=incoming_payload["modality"],
        easy_apply=bool(job.get("easy_apply", False)),
        applicant_count=int(job.get("applicant_count") or 0),
        applicant_count_raw=job.get("applicant_count_raw"),
        posted_at=job.get("posted_at"),
        first_seen_at=now,
        last_seen_at=now,
        job_content_hash=content_hash,
    )
    db.add(posting)
    db.flush()
    return posting


def _job_payload(posting: models.JobPosting) -> dict:
    return {
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "description": posting.description,
        "modality": posting.modality,
        "easy_apply": posting.easy_apply,
        "applicant_count": posting.applicant_count,
        "canonical_url": posting.canonical_url,
    }


def _coerce_applicant_limit(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 100
    return max(numeric, 0)


def _is_over_applicant_limit(applicant_count: int | None, limit: int | None) -> bool:
    if limit is None:
        return False
    return int(applicant_count or 0) >= limit


def _needs_llm_refresh(result: models.SearchResult | None, posting: models.JobPosting | None) -> bool:
    if posting is None:
        return False
    if result is None:
        return True
    prior_hash = (result.llm_analysis_hash or "").strip()
    current_hash = (posting.job_content_hash or "").strip()
    return prior_hash != current_hash


def _cached_ai_payload(
    posting: models.JobPosting,
    result: models.SearchResult | None,
    prompt_version: str,
) -> dict | None:
    if result is None:
        return None
    if _needs_llm_refresh(result, posting):
        return None
    return {
        "job_category": posting.job_category,
        "job_subcategory": posting.job_subcategory,
        "llm_fit_score": result.llm_fit_score,
        "fit_reasons": result.fit_reasons_json or [],
        "gap_notes": result.gap_notes_json or [],
        "role_alignment": result.role_alignment_json or [],
        "llm_status": result.llm_status or "fallback",
        "llm_analysis_hash": result.llm_analysis_hash or posting.job_content_hash,
        "llm_model": None,
        "llm_prompt_version": prompt_version,
        "llm_error": None,
    }


def _pre_llm_rank_score(
    *,
    deterministic_score: float,
    recency_score: float,
    location_score: float,
    personalization_score: float,
) -> float:
    value = (
        (0.55 * deterministic_score)
        + (0.20 * personalization_score)
        + (0.15 * location_score)
        + (0.10 * recency_score)
    )
    return round(value, 2)


def _recency_score(posted_at: datetime | None) -> float:
    if not posted_at:
        return 30.0

    age_hours = max((datetime.utcnow() - posted_at).total_seconds() / 3600.0, 0.0)
    if age_hours <= 1:
        return 100.0
    if age_hours <= 3:
        return 85.0
    if age_hours <= 8:
        return 70.0
    if age_hours <= 24:
        return 55.0
    if age_hours <= 72:
        return 40.0
    return 25.0


def _location_score(
    job_location: str | None,
    modality: str | None,
    search_city: str | None,
    search_country: str | None,
) -> float:
    loc = (job_location or "").lower()
    city = (search_city or "").lower().strip()
    country = (search_country or "").lower().strip()

    if city and city in loc:
        return 100.0
    if country and country in loc:
        return 80.0
    if (modality or "").lower() in {"remote", "hybrid"}:
        return 70.0
    return 40.0


def _final_score(
    *,
    deterministic_score: float,
    llm_score: float,
    recency_score: float,
    location_score: float,
    personalization_score: float,
    llm_status: str,
    time_window_hours: int,
) -> float:
    long_term = int(time_window_hours or 24) >= 168
    if llm_status == "ok":
        if long_term:
            value = (
                (0.55 * llm_score)
                + (0.15 * deterministic_score)
                + (0.05 * recency_score)
                + (0.10 * location_score)
                + (0.15 * personalization_score)
            )
        else:
            value = (
                (0.52 * llm_score)
                + (0.18 * deterministic_score)
                + (0.08 * recency_score)
                + (0.10 * location_score)
                + (0.12 * personalization_score)
            )
    else:
        if long_term:
            value = (
                (0.55 * deterministic_score)
                + (0.08 * recency_score)
                + (0.12 * location_score)
                + (0.25 * personalization_score)
            )
        else:
            value = (
                (0.60 * deterministic_score)
                + (0.12 * recency_score)
                + (0.10 * location_score)
                + (0.18 * personalization_score)
            )
    return round(value, 2)


def _resolve_llm_fit_score(
    value: float | int | str | None,
    *,
    fallback_score: float,
    llm_status: str | None,
) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(fallback_score)

    numeric = min(max(numeric, 0.0), 100.0)
    if numeric <= 0 and (llm_status or "fallback") == "fallback" and fallback_score > 0:
        numeric = float(fallback_score)
    return round(numeric, 2)
