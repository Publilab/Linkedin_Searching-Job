from __future__ import annotations

import hashlib
import re
from typing import Any

from app.services.llm import LLMClientError, get_llm_client
from app.services.llm.prompts import build_job_prompt
from app.services.llm.schemas import LLMJobEvaluation
from app.services.runtime_settings import load_runtime_llm_config


def evaluate_job_fit(
    profile_summary: dict[str, Any],
    profile_analysis: dict[str, Any],
    job_payload: dict[str, Any],
    deterministic_score: float,
    *,
    allow_llm: bool = True,
) -> dict[str, Any]:
    analysis_hash = compute_job_content_hash(job_payload)
    runtime_cfg = load_runtime_llm_config()

    fallback = _fallback_result(
        job_payload,
        deterministic_score,
        analysis_hash,
        error=None,
        prompt_version=runtime_cfg.prompt_version,
    )
    if not allow_llm:
        return fallback

    client = get_llm_client()
    if not client.enabled:
        fallback["llm_error"] = f"LLM disabled or missing {runtime_cfg.provider} configuration"
        return fallback

    prompt = build_job_prompt(
        prompt_version=runtime_cfg.prompt_version,
        profile_summary=profile_summary,
        profile_analysis=profile_analysis,
        job_payload=job_payload,
        deterministic_score=deterministic_score,
    )

    try:
        payload = client.generate_json(prompt)
        parsed = LLMJobEvaluation.model_validate(payload)

        category, subcategory = _infer_job_category(job_payload)
        if parsed.job_category:
            category = parsed.job_category.strip() or category
        if parsed.job_subcategory:
            subcategory = parsed.job_subcategory.strip() or subcategory

        llm_fit = _clamp_score(parsed.llm_fit_score)
        return {
            "job_category": category,
            "job_subcategory": subcategory,
            "llm_fit_score": llm_fit,
            "fit_reasons": _clean_list(parsed.fit_reasons)[:8],
            "gap_notes": _clean_list(parsed.gap_notes)[:8],
            "role_alignment": _clean_list(parsed.role_alignment)[:8],
            "llm_status": "ok",
            "llm_analysis_hash": analysis_hash,
            "llm_model": runtime_cfg.model,
            "llm_prompt_version": runtime_cfg.prompt_version,
            "llm_error": None,
        }
    except (LLMClientError, ValueError) as exc:
        fallback["llm_error"] = str(exc)
        return fallback


def compute_job_content_hash(job_payload: dict[str, Any]) -> str:
    text = "|".join(
        [
            str(job_payload.get("title") or "").strip().lower(),
            str(job_payload.get("company") or "").strip().lower(),
            str(job_payload.get("location") or "").strip().lower(),
            str(job_payload.get("description") or "").strip().lower(),
            str(job_payload.get("modality") or "").strip().lower(),
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fallback_result(
    job_payload: dict[str, Any],
    deterministic_score: float,
    analysis_hash: str,
    *,
    error: str | None,
    prompt_version: str,
) -> dict[str, Any]:
    category, subcategory = _infer_job_category(job_payload)
    title = str(job_payload.get("title") or "").strip() or "Role"

    return {
        "job_category": category,
        "job_subcategory": subcategory,
        "llm_fit_score": _clamp_score(deterministic_score),
        "fit_reasons": [f"Deterministic match based on CV overlap for {title}"],
        "gap_notes": [],
        "role_alignment": [category] if category else [],
        "llm_status": "fallback",
        "llm_analysis_hash": analysis_hash,
        "llm_model": None,
        "llm_prompt_version": prompt_version,
        "llm_error": error,
    }


def _infer_job_category(job_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    corpus = f"{job_payload.get('title', '')} {job_payload.get('description', '')}".lower()

    rules: list[tuple[set[str], tuple[str, str]]] = [
        ({"data", "analytics", "analyst", "bi", "tableau", "power bi"}, ("Data", "Analytics")),
        ({"backend", "api", "python", "java", "node", "microservices"}, ("Engineering", "Backend")),
        ({"frontend", "react", "next.js", "vue", "angular"}, ("Engineering", "Frontend")),
        ({"full stack", "fullstack"}, ("Engineering", "Full Stack")),
        ({"devops", "sre", "kubernetes", "terraform", "cloud"}, ("Engineering", "DevOps")),
        ({"product manager", "product owner", "roadmap"}, ("Product", "Product Management")),
        ({"designer", "ux", "ui"}, ("Design", "UX/UI")),
        ({"marketing", "seo", "growth"}, ("Marketing", "Digital Marketing")),
        ({"sales", "account executive", "business development"}, ("Sales", "Commercial")),
    ]

    for tokens, output in rules:
        for token in tokens:
            if token in corpus:
                return output

    if re.search(r"\b(engineer|developer)\b", corpus):
        return "Engineering", "General"

    return "General", "Other"


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _clamp_score(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(numeric, 0.0), 100.0), 2)
