from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.config import settings
from app.services.llm import LLMClientError, get_llm_client
from app.services.llm.pii import redact_pii
from app.services.llm.prompts import build_profile_prompt
from app.services.llm.schemas import LLMCVExtraction


def analyze_profile(raw_text: str, summary: dict[str, Any]) -> dict[str, Any]:
    normalized_summary = _normalize_summary(summary)
    redacted_text = redact_pii(raw_text)
    fingerprint = _profile_fingerprint(normalized_summary)

    client = get_llm_client()
    if not client.enabled:
        return _fallback_bundle(
            normalized_summary,
            fingerprint=fingerprint,
            error=f"LLM disabled or missing {settings.llm_provider} configuration",
        )

    prompt = build_profile_prompt(
        prompt_version=settings.llm_prompt_version,
        cv_text=redacted_text,
        current_summary=normalized_summary,
    )

    try:
        payload = client.generate_json(prompt)
        parsed = LLMCVExtraction.model_validate(payload)
        merged_summary = _merge_summary(normalized_summary, parsed)
        inferred_roles = _infer_roles(merged_summary)

        strategy = {
            "recommended_queries": _clean_list(
                list(parsed.recommended_queries or []) + _fallback_queries(merged_summary)
            )[:18]
        }

        target_roles = _clean_list(list(parsed.target_roles or []) + inferred_roles)[:8]
        secondary_candidates = _clean_list(list(parsed.secondary_roles or []) + inferred_roles)[:12]
        secondary_roles = [role for role in secondary_candidates if role not in target_roles][:8]

        analysis = {
            "target_roles": target_roles,
            "secondary_roles": secondary_roles,
            "seniority": (parsed.seniority or "unknown").strip().lower(),
            "industries": _clean_list(parsed.industries)[:8],
            "strengths": _clean_list(parsed.strengths)[:12],
            "skill_gaps": _clean_list(parsed.skill_gaps)[:12],
            "recommended_queries": strategy["recommended_queries"],
            "llm_status": "ok",
        }

        llm_profile_json = {
            "target_roles": analysis["target_roles"],
            "secondary_roles": analysis["secondary_roles"],
            "seniority": analysis["seniority"],
            "industries": analysis["industries"],
            "strengths": analysis["strengths"],
            "skill_gaps": analysis["skill_gaps"],
            "highlights": merged_summary["highlights"],
            "skills": merged_summary["skills"],
            "experience": merged_summary["experience"],
            "education": merged_summary["education"],
            "languages": merged_summary["languages"],
        }

        return {
            "summary": merged_summary,
            "analysis": analysis,
            "llm_profile_json": llm_profile_json,
            "llm_strategy_json": strategy,
            "profile_fingerprint": fingerprint,
            "llm_model": settings.llm_model,
            "llm_prompt_version": settings.llm_prompt_version,
            "llm_status": "ok",
            "llm_error": None,
        }
    except (LLMClientError, ValueError) as exc:
        return _fallback_bundle(normalized_summary, fingerprint=fingerprint, error=str(exc))


def _fallback_bundle(summary: dict[str, Any], *, fingerprint: str, error: str) -> dict[str, Any]:
    target_roles = _infer_roles(summary)
    strategy = {"recommended_queries": _fallback_queries(summary)}

    analysis = {
        "target_roles": target_roles[:5],
        "secondary_roles": target_roles[5:10],
        "seniority": _infer_seniority(summary),
        "industries": _infer_industries(summary),
        "strengths": summary.get("skills", [])[:10],
        "skill_gaps": _infer_skill_gaps(summary),
        "recommended_queries": strategy["recommended_queries"],
        "llm_status": "fallback",
    }

    llm_profile_json = {
        "target_roles": analysis["target_roles"],
        "secondary_roles": analysis["secondary_roles"],
        "seniority": analysis["seniority"],
        "industries": analysis["industries"],
        "strengths": analysis["strengths"],
        "skill_gaps": analysis["skill_gaps"],
        "highlights": summary.get("highlights", []),
        "skills": summary.get("skills", []),
        "experience": summary.get("experience", []),
        "education": summary.get("education", []),
        "languages": summary.get("languages", []),
    }

    return {
        "summary": summary,
        "analysis": analysis,
        "llm_profile_json": llm_profile_json,
        "llm_strategy_json": strategy,
        "profile_fingerprint": fingerprint,
        "llm_model": None,
        "llm_prompt_version": settings.llm_prompt_version,
        "llm_status": "fallback",
        "llm_error": error,
    }


def _normalize_summary(summary: dict[str, Any]) -> dict[str, list[str]]:
    base = {
        "highlights": _clean_list(summary.get("highlights", [])),
        "skills": _clean_list(summary.get("skills", [])),
        "experience": _clean_list(summary.get("experience", [])),
        "education": _clean_list(summary.get("education", [])),
        "languages": _clean_list(summary.get("languages", [])),
    }
    return base


def _merge_summary(base: dict[str, list[str]], llm: LLMCVExtraction) -> dict[str, list[str]]:
    merged = {
        "highlights": _clean_list(llm.highlights)[:14] or base["highlights"],
        "skills": _clean_list(llm.skills)[:40] or base["skills"],
        "experience": _clean_list(llm.experience)[:20] or base["experience"],
        "education": _clean_list(llm.education)[:12] or base["education"],
        "languages": _clean_list(llm.languages)[:10] or base["languages"],
    }
    return merged


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


def _profile_fingerprint(summary: dict[str, Any]) -> str:
    payload = json.dumps(summary, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _infer_roles(summary: dict[str, Any]) -> list[str]:
    seeds = summary.get("experience", []) + summary.get("highlights", []) + summary.get("education", [])
    role_tokens = [
        "engineer",
        "developer",
        "analyst",
        "scientist",
        "manager",
        "consultant",
        "architect",
        "specialist",
        "administrador",
        "administradora",
        "coordinador",
        "coordinadora",
        "jefe",
        "direct",
        "encargad",
        "publico",
        "publica",
        "academico",
        "academica",
        "docente",
        "profesor",
        "profesora",
        "instructor",
        "relator",
        "rrhh",
        "recursos humanos",
        "human resources",
        "talento humano",
        "gestion de personas",
        "people operations",
        "reclutamiento",
        "seleccion",
    ]

    roles: list[str] = []
    has_public_admin = False
    has_academic = False
    has_hr = False
    for line in seeds:
        if not isinstance(line, str):
            continue
        cleaned = " ".join(line.split())
        if not cleaned:
            continue

        candidates = [cleaned]
        normalized = _normalize_role_candidate(cleaned)
        if normalized and normalized.lower() != cleaned.lower():
            candidates.append(normalized)

        for candidate in candidates:
            low = candidate.lower()

            if not _is_valid_role_phrase(candidate):
                continue

            if any(token in low for token in role_tokens):
                roles.append(candidate)

            if "administrador publico" in low or "administrador público" in low:
                has_public_admin = True

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
                has_academic = True

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
                has_hr = True

    priority_roles: list[str] = []
    if has_public_admin:
        priority_roles.extend(
            [
                "Administrador Publico",
                "Especialista en Gestion Publica",
                "Analista de Politicas Publicas",
                "Coordinador de Programas Publicos",
            ]
        )
    if has_academic:
        priority_roles.extend(
            [
                "Academico",
                "Docente Universitario",
                "Relator de Capacitacion",
            ]
        )
    if has_hr:
        priority_roles.extend(
            [
                "Analista de Recursos Humanos",
                "Generalista de Recursos Humanos",
                "People Operations Specialist",
            ]
        )

    combined_roles = _clean_list(priority_roles + roles)
    if not combined_roles:
        skills = summary.get("skills", [])[:4]
        if skills:
            combined_roles = [f"{skills[0]} specialist"]

    return combined_roles


def _normalize_role_candidate(value: str) -> str:
    cleaned = " ".join(value.split()).strip(" -|,;")
    if not cleaned:
        return ""

    # Keep role prefix when experience lines include organization/date suffixes.
    base = re.split(r"\b(?:19|20)\d{2}\b", cleaned, maxsplit=1)[0].strip(" -|,;")
    low = base.lower()
    for sep in [" at ", " en ", " - ", " | ", ","]:
        if sep in low:
            idx = low.index(sep)
            part = base[:idx].strip(" -|,;")
            if part:
                base = part
                low = base.lower()
                break
    return base


def _infer_seniority(summary: dict[str, Any]) -> str:
    corpus = " ".join(summary.get("experience", []) + summary.get("highlights", [])).lower()
    if re.search(r"\b(lead|principal|staff|jefe|director|directora)\b", corpus):
        return "lead"
    if re.search(r"\b(senior|sr\.?|expert)\b", corpus):
        return "senior"
    if re.search(r"\b(junior|jr\.?|trainee|intern|practicante)\b", corpus):
        return "junior"
    if corpus:
        return "mid"
    return "unknown"


def _infer_industries(summary: dict[str, Any]) -> list[str]:
    corpus = " ".join(summary.get("experience", []) + summary.get("education", [])).lower()
    mapping = {
        "finance": "Finance",
        "bank": "Finance",
        "health": "Healthcare",
        "hospital": "Healthcare",
        "retail": "Retail",
        "marketing": "Marketing",
        "ecommerce": "E-commerce",
        "software": "Software",
        "data": "Data & Analytics",
        "logistics": "Logistics",
        "public": "Public Sector",
        "municip": "Public Sector",
        "gobierno": "Public Sector",
        "ministerio": "Public Sector",
        "estado": "Public Sector",
        "rrhh": "Human Resources",
        "recursos humanos": "Human Resources",
        "human resources": "Human Resources",
        "talento humano": "Human Resources",
        "academ": "Education",
        "docenc": "Education",
        "universidad": "Education",
        "educacion": "Education",
        "educación": "Education",
    }
    out: list[str] = []
    for token, label in mapping.items():
        if token in corpus:
            out.append(label)
    return _clean_list(out)


def _infer_skill_gaps(summary: dict[str, Any]) -> list[str]:
    skills = {s.lower() for s in summary.get("skills", [])}
    recommendations = []
    if not any(s in skills for s in {"aws", "azure", "gcp"}):
        recommendations.append("Cloud platform (AWS, Azure or GCP)")
    if "docker" not in skills:
        recommendations.append("Docker")
    if "kubernetes" not in skills:
        recommendations.append("Kubernetes")
    if not any(s in skills for s in {"english", "ingles", "inglés"}):
        recommendations.append("Professional English")
    return recommendations[:8]


def _fallback_queries(summary: dict[str, Any]) -> list[str]:
    roles = _infer_roles(summary)[:8]
    skills = summary.get("skills", [])[:12]
    education_queries = _extract_education_queries(summary.get("education", []))
    queries: list[str] = []

    primary_skill = _select_primary_skill(skills)

    for role in roles:
        queries.append(role)
        if primary_skill:
            queries.append(f"{role} {primary_skill}")

    queries.extend(education_queries)

    for skill in skills:
        if skill.lower() in {"excel", "microsoft office", "office"}:
            continue
        queries.append(skill)

    cleaned = _clean_list(queries)
    return cleaned[:18] or ["public policy analyst"]


def _extract_education_queries(education_lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in education_lines:
        if not isinstance(line, str):
            continue
        cleaned = " ".join(line.split())
        low = cleaned.lower()
        if not cleaned:
            continue

        if len(cleaned) <= 90 and "•" not in cleaned and not re.search(r"\b(19|20)\d{2}\b", low):
            out.append(cleaned)

        if "administrador publico" in low or "administrador público" in low:
            out.extend(
                [
                    "Administrador Publico",
                    "Gestion Publica",
                    "Politicas Publicas",
                    "Gobierno",
                    "Municipal",
                    "Sector Publico",
                ]
            )

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

    return _clean_list(out)


def _select_primary_skill(skills: list[str]) -> str | None:
    if not skills:
        return None

    preferred = [
        "python",
        "sql",
        "r",
        "analisis de datos",
        "data",
        "gestion publica",
        "politicas publicas",
    ]
    low_skills = [s.lower() for s in skills]

    for candidate in preferred:
        for idx, skill in enumerate(low_skills):
            if candidate == skill or candidate in skill:
                return skills[idx]

    for skill in skills:
        if skill.lower() not in {"excel", "microsoft office", "office"}:
            return skill

    return skills[0]



def _is_valid_role_phrase(value: str) -> bool:
    cleaned = " ".join(value.split())
    if not cleaned:
        return False
    if len(cleaned) > 100:
        return False

    low = cleaned.lower()
    if "•" in cleaned:
        return False
    if re.search(r"\b(19|20)\d{2}\b", low):
        return False
    if re.search(r"\b(university|universidad|instituto|consulting|s\.a\.)\b", low):
        return False
    if re.search(
        r"\b(evaluacion|evaluaciones|obtuve|logr[eé]|diseñ[eé]|lider[eé]|mediante|reflejando|mejorando)\b",
        low,
    ):
        return False

    token_count = len(cleaned.split())
    return 1 <= token_count <= 9
