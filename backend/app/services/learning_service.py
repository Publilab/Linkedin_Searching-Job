from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

EVENT_WEIGHTS: dict[str, float] = {
    "open": 1.0,
    "save": 2.0,
    "apply": 3.0,
    "dismiss": -2.0,
    "check": 0.5,
    "uncheck": -0.5,
    "bulk_check": 0.25,
    "bulk_uncheck": -0.25,
}

STOPWORDS = {
    "with",
    "para",
    "from",
    "this",
    "that",
    "your",
    "have",
    "will",
    "and",
    "the",
    "for",
    "you",
    "are",
    "las",
    "los",
    "con",
    "por",
    "que",
    "una",
    "del",
    "para",
    "de",
    "una",
    "sobre",
    "team",
    "role",
    "work",
    "trabajo",
    "cargo",
}


def default_learned_preferences() -> dict[str, Any]:
    return {
        "event_counts": {},
        "title_scores": {},
        "category_scores": {},
        "subcategory_scores": {},
        "location_scores": {},
        "company_scores": {},
        "token_scores": {},
        "last_event_type": None,
        "last_updated_at": None,
    }


def normalize_learned_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = default_learned_preferences()
    if not isinstance(payload, dict):
        return base

    for key in [
        "event_counts",
        "title_scores",
        "category_scores",
        "subcategory_scores",
        "location_scores",
        "company_scores",
        "token_scores",
    ]:
        value = payload.get(key)
        base[key] = value if isinstance(value, dict) else {}

    last_event_type = payload.get("last_event_type")
    base["last_event_type"] = str(last_event_type) if isinstance(last_event_type, str) else None

    last_updated_at = payload.get("last_updated_at")
    base["last_updated_at"] = str(last_updated_at) if isinstance(last_updated_at, str) else None

    _coerce_numeric_map(base["event_counts"], as_int=True)
    for key in [
        "title_scores",
        "category_scores",
        "subcategory_scores",
        "location_scores",
        "company_scores",
        "token_scores",
    ]:
        _coerce_numeric_map(base[key], as_int=False)

    return base


def update_preferences_from_interaction(
    db: Session,
    *,
    cv_id: str,
    event_type: str,
    job: models.JobPosting | None,
    dwell_ms: int | None,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
    if not profile:
        return default_learned_preferences()

    prefs = normalize_learned_preferences(profile.learned_preferences_json)
    event_key = _normalize_key(event_type)
    if not event_key:
        event_key = "open"

    signal = _event_signal(event_key, dwell_ms)
    _inc_event_count(prefs, event_key)

    if job is not None:
        _apply_job_signal(prefs, job, signal)

    if meta and isinstance(meta, dict):
        _apply_meta_signal(prefs, meta, signal)

    prefs["last_event_type"] = event_key
    prefs["last_updated_at"] = datetime.utcnow().isoformat()

    profile.learned_preferences_json = _trim_preference_maps(prefs)
    profile.updated_at = datetime.utcnow()
    db.add(profile)
    return profile.learned_preferences_json


def preferred_query_seeds(preferences: dict[str, Any] | None, *, limit: int = 8) -> list[str]:
    prefs = normalize_learned_preferences(preferences)

    titles = _top_positive_keys(prefs.get("title_scores"), limit=max(limit, 4))
    categories = _top_positive_keys(prefs.get("category_scores"), limit=4)
    tokens = _top_positive_keys(prefs.get("token_scores"), limit=8)

    out: list[str] = []
    for item in titles:
        out.append(item)
    for item in categories:
        if len(out) >= limit:
            break
        if item and item.lower() not in {q.lower() for q in out}:
            out.append(item)
    for token in tokens:
        if len(out) >= limit:
            break
        if not token or len(token) < 5:
            continue
        if token.lower() in {q.lower() for q in out}:
            continue
        out.append(token)

    return out[:limit]


def personalization_score_for_job(job: models.JobPosting, preferences: dict[str, Any] | None) -> float:
    prefs = normalize_learned_preferences(preferences)

    weighted_parts: list[tuple[float, float]] = []

    title_key = _normalize_key(job.title)
    if title_key:
        title_weight = _lookup_score(prefs.get("title_scores"), title_key)
        if title_weight is not None:
            weighted_parts.append((_preference_weight_to_score(title_weight), 2.4))

    category_key = _normalize_key(job.job_category)
    if category_key:
        category_weight = _lookup_score(prefs.get("category_scores"), category_key)
        if category_weight is not None:
            weighted_parts.append((_preference_weight_to_score(category_weight), 1.4))

    subcategory_key = _normalize_key(job.job_subcategory)
    if subcategory_key:
        subcategory_weight = _lookup_score(prefs.get("subcategory_scores"), subcategory_key)
        if subcategory_weight is not None:
            weighted_parts.append((_preference_weight_to_score(subcategory_weight), 1.2))

    location_key = _normalize_key(job.location)
    if location_key:
        location_weight = _lookup_score(prefs.get("location_scores"), location_key)
        if location_weight is not None:
            weighted_parts.append((_preference_weight_to_score(location_weight), 0.9))

    company_key = _normalize_key(job.company)
    if company_key:
        company_weight = _lookup_score(prefs.get("company_scores"), company_key)
        if company_weight is not None:
            weighted_parts.append((_preference_weight_to_score(company_weight), 0.7))

    token_map = prefs.get("token_scores") if isinstance(prefs.get("token_scores"), dict) else {}
    token_hits: list[float] = []
    for token in _job_tokens(job):
        token_weight = _lookup_score(token_map, token)
        if token_weight is None:
            continue
        token_hits.append(token_weight)
    if token_hits:
        avg_token_weight = sum(token_hits) / len(token_hits)
        weighted_parts.append((_preference_weight_to_score(avg_token_weight), 1.8))

    if not weighted_parts:
        return 50.0

    score_sum = sum(score * weight for score, weight in weighted_parts)
    weight_sum = sum(weight for _, weight in weighted_parts)
    if weight_sum <= 0:
        return 50.0

    return round(min(max(score_sum / weight_sum, 0.0), 100.0), 2)


def summarize_preference_strengths(preferences: dict[str, Any] | None) -> dict[str, list[dict[str, float]]]:
    prefs = normalize_learned_preferences(preferences)
    return {
        "top_titles": _top_positive_pairs(prefs.get("title_scores"), limit=6),
        "top_categories": _top_positive_pairs(prefs.get("category_scores"), limit=6),
        "top_tokens": _top_positive_pairs(prefs.get("token_scores"), limit=10),
        "top_locations": _top_positive_pairs(prefs.get("location_scores"), limit=6),
    }


def _event_signal(event_type: str, dwell_ms: int | None) -> float:
    signal = float(EVENT_WEIGHTS.get(event_type, 0.0))
    if event_type == "open" and dwell_ms is not None:
        if dwell_ms >= 120_000:
            signal += 1.2
        elif dwell_ms >= 60_000:
            signal += 0.8
        elif dwell_ms >= 30_000:
            signal += 0.5
    return signal


def _apply_job_signal(prefs: dict[str, Any], job: models.JobPosting, signal: float) -> None:
    _add_score(prefs["title_scores"], _normalize_key(job.title), signal, clamp=(-25.0, 60.0))
    _add_score(prefs["category_scores"], _normalize_key(job.job_category), signal * 0.8, clamp=(-25.0, 50.0))
    _add_score(prefs["subcategory_scores"], _normalize_key(job.job_subcategory), signal * 0.7, clamp=(-25.0, 45.0))
    _add_score(prefs["location_scores"], _normalize_key(job.location), signal * 0.5, clamp=(-20.0, 40.0))
    _add_score(prefs["company_scores"], _normalize_key(job.company), signal * 0.4, clamp=(-15.0, 35.0))

    token_delta = signal * 0.4
    for token in _job_tokens(job):
        _add_score(prefs["token_scores"], token, token_delta, clamp=(-15.0, 35.0))


def _apply_meta_signal(prefs: dict[str, Any], meta: dict[str, Any], signal: float) -> None:
    for field, key in [
        ("query", "title_scores"),
        ("query_text", "title_scores"),
        ("category", "category_scores"),
        ("location", "location_scores"),
    ]:
        value = meta.get(field)
        normalized = _normalize_key(value)
        if not normalized:
            continue
        _add_score(prefs[key], normalized, signal * 0.3, clamp=(-10.0, 20.0))


def _inc_event_count(prefs: dict[str, Any], event_type: str) -> None:
    counts = prefs.get("event_counts")
    if not isinstance(counts, dict):
        counts = {}
        prefs["event_counts"] = counts
    current = int(counts.get(event_type) or 0)
    counts[event_type] = current + 1


def _coerce_numeric_map(store: dict[str, Any], *, as_int: bool) -> None:
    keys = list(store.keys())
    for key in keys:
        normalized_key = _normalize_key(key)
        if not normalized_key:
            store.pop(key, None)
            continue

        raw_value = store.get(key)
        try:
            numeric = int(raw_value) if as_int else float(raw_value)
        except (TypeError, ValueError):
            store.pop(key, None)
            continue

        store.pop(key, None)
        store[normalized_key] = numeric


def _trim_preference_maps(prefs: dict[str, Any], *, keep: int = 120) -> dict[str, Any]:
    for key in [
        "title_scores",
        "category_scores",
        "subcategory_scores",
        "location_scores",
        "company_scores",
        "token_scores",
    ]:
        store = prefs.get(key)
        if not isinstance(store, dict):
            prefs[key] = {}
            continue
        if len(store) <= keep:
            continue
        ranked = sorted(store.items(), key=lambda item: abs(float(item[1])), reverse=True)
        prefs[key] = {k: float(v) for k, v in ranked[:keep]}

    return prefs


def _top_positive_keys(store: dict[str, Any] | None, *, limit: int) -> list[str]:
    if not isinstance(store, dict):
        return []
    ranked = sorted(store.items(), key=lambda item: float(item[1]), reverse=True)
    return [str(key) for key, value in ranked if float(value) > 0][:limit]


def _top_positive_pairs(store: dict[str, Any] | None, *, limit: int) -> list[dict[str, float]]:
    if not isinstance(store, dict):
        return []
    ranked = sorted(store.items(), key=lambda item: float(item[1]), reverse=True)
    out: list[dict[str, float]] = []
    for key, value in ranked:
        numeric = float(value)
        if numeric <= 0:
            continue
        out.append({"label": str(key), "score": round(numeric, 2)})
        if len(out) >= limit:
            break
    return out


def _lookup_score(store: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(store, dict):
        return None
    value = store.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _preference_weight_to_score(weight: float) -> float:
    # Neutral history => 50. Positive and negative signals move around that center.
    value = 50.0 + (float(weight) * 6.5)
    return min(max(value, 0.0), 100.0)


def _add_score(store: dict[str, Any], key: str | None, delta: float, *, clamp: tuple[float, float]) -> None:
    if not key:
        return
    current = 0.0
    if key in store:
        try:
            current = float(store.get(key) or 0.0)
        except (TypeError, ValueError):
            current = 0.0

    next_value = current + float(delta)
    min_value, max_value = clamp
    next_value = min(max(next_value, float(min_value)), float(max_value))
    store[key] = round(next_value, 3)


def _job_tokens(job: models.JobPosting) -> list[str]:
    corpus = f"{job.title or ''} {job.description or ''}"
    tokens = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9+.#_-]{4,}", corpus.lower())

    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip("+-_#. ")
        if not token or token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 40:
            break
    return out


def _normalize_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split()).strip().lower()
    if not cleaned:
        return ""
    if len(cleaned) > 160:
        cleaned = cleaned[:160].strip()
    return cleaned
