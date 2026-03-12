from __future__ import annotations

from typing import Any

import httpx

STATIC_DEMAND = [
    {"role": "Data Analyst", "demand_score": 88.0, "tags": ["data", "analytics", "bi"]},
    {"role": "Backend Engineer", "demand_score": 86.0, "tags": ["backend", "api", "python", "java"]},
    {"role": "Project Manager", "demand_score": 84.0, "tags": ["project", "manager", "gestion"]},
    {"role": "Public Policy Analyst", "demand_score": 80.0, "tags": ["public", "policy", "gobierno"]},
    {"role": "Procurement Specialist", "demand_score": 77.0, "tags": ["procurement", "compras", "licitaciones"]},
    {
        "role": "Human Resources Analyst",
        "demand_score": 79.0,
        "tags": ["rrhh", "recursos", "humanos", "human", "resources", "talento"],
    },
    {
        "role": "People Operations Coordinator",
        "demand_score": 76.0,
        "tags": ["people", "operations", "rrhh", "talento", "gestion"],
    },
    {
        "role": "Academic Coordinator",
        "demand_score": 73.0,
        "tags": ["academico", "docente", "educacion", "formacion", "capacitacion"],
    },
    {"role": "Operations Coordinator", "demand_score": 75.0, "tags": ["operations", "coordinador", "process"]},
    {"role": "Business Analyst", "demand_score": 74.0, "tags": ["business", "analyst", "process"]},
]


def build_search_strategy(
    summary: dict[str, Any],
    analysis: dict[str, Any],
    *,
    max_terms: int = 6,
) -> dict[str, Any]:
    role_focus = _build_role_focus(summary, analysis)
    candidates = role_focus[:max_terms] or summary.get("skills", [])[:max_terms]

    internet_roles = _fetch_internet_demand(candidates)
    if internet_roles:
        market_roles = internet_roles
    else:
        market_roles = _fallback_demand(candidates)

    recommended_queries = _dedupe(
        list(analysis.get("recommended_queries", []) or [])
        + role_focus
        + [item["role"] for item in market_roles]
    )

    return {
        "role_focus": role_focus[:12],
        "recommended_queries": recommended_queries[:20],
        "market_roles": market_roles[:12],
    }


def _build_role_focus(summary: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    roles = []
    roles.extend(analysis.get("target_roles", []) or [])
    roles.extend(analysis.get("secondary_roles", []) or [])
    roles.extend(summary.get("experience", [])[:6])
    roles.extend(summary.get("education", [])[:6])

    cleaned = [r for r in _dedupe(roles) if _is_valid_focus_phrase(r)]
    return cleaned


def _fetch_internet_demand(terms: list[str]) -> list[dict[str, Any]]:
    if not terms:
        return []

    out: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=6.0, follow_redirects=True) as client:
            for term in terms[:4]:
                response = client.get("https://remotive.com/api/remote-jobs", params={"search": term})
                if response.status_code != 200:
                    continue
                data = response.json()
                jobs = data.get("jobs")
                if not isinstance(jobs, list):
                    continue
                count = len(jobs)
                if count <= 0:
                    continue
                score = min(100.0, 30.0 + (count * 1.8))
                out.append(
                    {
                        "role": term,
                        "demand_score": round(score, 2),
                        "source": "internet_remotive",
                        "rationale": f"{count} matching postings in Remotive sample",
                    }
                )
    except Exception:
        return []

    out.sort(key=lambda item: item["demand_score"], reverse=True)
    return out


def _fallback_demand(terms: list[str]) -> list[dict[str, Any]]:
    tokens = {token for term in terms for token in term.lower().split() if len(token) > 2}
    scored: list[dict[str, Any]] = []

    for item in STATIC_DEMAND:
        overlap = len(tokens & set(item["tags"]))
        boost = overlap * 4.0
        scored.append(
            {
                "role": item["role"],
                "demand_score": round(min(100.0, item["demand_score"] + boost), 2),
                "source": "fallback_catalog",
                "rationale": "Static demand baseline weighted by profile overlap",
            }
        )

    scored.sort(key=lambda entry: entry["demand_score"], reverse=True)
    return scored


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out



def _is_valid_focus_phrase(value: str) -> bool:
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return False
    if len(cleaned) > 100:
        return False

    low = cleaned.lower()
    banned = ["universidad", "university", "instituto", "municipalidad", "•"]
    if any(token in low for token in banned):
        return False
    return True
