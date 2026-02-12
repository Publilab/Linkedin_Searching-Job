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
        eligible_found = 0
        llm_budget = max(int(runtime_cfg.max_jobs_per_run), 0)

        for job in scraped_jobs.values():
            posting = _upsert_posting(db, job)
            if (posting.applicant_count or 0) >= 100:
                # Exclude crowded offers by product rule.
                db.commit()
                continue

            eligible_found += 1
            score, breakdown = compute_match(profile_summary, job)

            result = db.scalar(
                select(models.SearchResult).where(
                    models.SearchResult.search_config_id == search_id_local,
                    models.SearchResult.job_posting_id == posting.id,
                )
            )

            posting_id = posting.id
            job_payload = _job_payload(posting)

            should_run_llm = False
            if llm_budget > 0:
                prior_hash = (result.llm_analysis_hash if result else "") or ""
                current_hash = posting.job_content_hash or ""
                should_run_llm = not result or prior_hash != current_hash

            cached_ai = None
            if not should_run_llm and result:
                cached_ai = {
                    "job_category": posting.job_category,
                    "job_subcategory": posting.job_subcategory,
                    "llm_fit_score": result.llm_fit_score,
                    "fit_reasons": result.fit_reasons_json or [],
                    "gap_notes": result.gap_notes_json or [],
                    "role_alignment": result.role_alignment_json or [],
                    "llm_status": result.llm_status or "fallback",
                    "llm_analysis_hash": result.llm_analysis_hash or posting.job_content_hash,
                    "llm_model": None,
                    "llm_prompt_version": runtime_cfg.prompt_version,
                    "llm_error": None,
                }

            # Persist immediate row changes and release SQLite write locks before external calls.
            db.commit()

            if should_run_llm:
                ai = evaluate_job_fit(
                    profile_summary,
                    profile_analysis,
                    job_payload,
                    score,
                    allow_llm=True,
                )
                llm_budget -= 1
            elif cached_ai:
                ai = cached_ai
            else:
                ai = evaluate_job_fit(
                    profile_summary,
                    profile_analysis,
                    job_payload,
                    score,
                    allow_llm=False,
                )

            llm_fit_score = _resolve_llm_fit_score(
                ai.get("llm_fit_score"),
                fallback_score=score,
                llm_status=ai.get("llm_status"),
            )

            posting = db.get(models.JobPosting, posting_id)
            if posting is None:
                posting = _upsert_posting(db, job)
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

            recency_score = _recency_score(posting.posted_at)
            location_score = _location_score(posting.location, posting.modality, search_city, search_country)
            personalization_score = personalization_score_for_job(posting, learned_preferences)
            final_score = _final_score(
                deterministic_score=score,
                llm_score=llm_fit_score,
                recency_score=recency_score,
                location_score=location_score,
                personalization_score=personalization_score,
                llm_status=str(ai.get("llm_status") or "fallback"),
            )
            breakdown_with_learning = {
                **(breakdown or {}),
                "personalization": personalization_score,
            }

            if result:
                result.match_percent = score
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
                    match_percent=score,
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
    llm_strategy: dict,
    extra_keywords: list[str],
    *,
    learned_preferences: dict | None = None,
) -> list[str]:
    strategy_queries = llm_strategy.get("recommended_queries", []) if isinstance(llm_strategy, dict) else []
    experience = profile_summary.get("experience", []) or []
    skills = profile_summary.get("skills", []) or []
    education = profile_summary.get("education", []) or []

    role_phrases = _extract_role_phrases(experience + education)
    education_focus = _extract_education_focus(education)
    learned_queries = preferred_query_seeds(learned_preferences, limit=8)

    seeds: list[str] = []
    # Highest priority: explicit strategy from profile analysis.
    seeds.extend([s for s in strategy_queries[:12] if isinstance(s, str)])

    # Learned preferences from interaction history.
    seeds.extend([s for s in learned_queries if isinstance(s, str)])

    # Then professional trajectory and academic formation.
    seeds.extend(role_phrases[:10])
    seeds.extend(education_focus[:8])

    # Keep legacy fallback signals.
    seeds.extend([s for s in experience[:6] if isinstance(s, str)])
    seeds.extend([s for s in skills[:10] if isinstance(s, str)])
    seeds.extend([s for s in education[:6] if isinstance(s, str)])
    seeds.extend([s for s in extra_keywords[:10] if isinstance(s, str)])

    normalized = []
    for value in seeds:
        cleaned = " ".join(value.split())
        if cleaned:
            normalized.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in normalized:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)

    if not deduped:
        deduped.append("software engineer")

    return deduped[:20]


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


def _extract_education_focus(education_lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in education_lines:
        if not isinstance(line, str):
            continue
        cleaned = " ".join(line.split())
        low = cleaned.lower()
        if not cleaned:
            continue

        if len(cleaned) <= 100 and "•" not in cleaned:
            out.append(cleaned)

        if "administrador publico" in low or "administrador público" in low:
            out.extend([
                "Administrador Publico",
                "Gestion Publica",
                "Politicas Publicas",
                "Gobierno",
                "Municipal",
            ])

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
                    "People Operations",
                ]
            )

        if any(
            token in low
            for token in [
                "academ",
                "docencia",
                "docente",
                "profesor",
                "profesora",
                "relator",
                "capacitacion",
                "capacitación",
            ]
        ):
            out.extend(
                [
                    "Academico",
                    "Docencia",
                    "Docente Universitario",
                    "Relator de Capacitacion",
                ]
            )

        if any(token in low for token in ["ingenier", "ingeniero", "ingeniera"]):
            out.append("Ingenieria")
        if "licenciado" in low or "licenciatura" in low:
            out.append("Licenciatura")

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
) -> float:
    if llm_status == "ok":
        value = (
            (0.50 * llm_score)
            + (0.20 * deterministic_score)
            + (0.10 * recency_score)
            + (0.10 * location_score)
            + (0.10 * personalization_score)
        )
    else:
        value = (
            (0.65 * deterministic_score)
            + (0.15 * recency_score)
            + (0.10 * location_score)
            + (0.10 * personalization_score)
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
