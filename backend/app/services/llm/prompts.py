from __future__ import annotations

import json


def build_profile_prompt(*, prompt_version: str, cv_text: str, current_summary: dict) -> str:
    payload = {
        "prompt_version": prompt_version,
        "task": "Extract and enrich candidate profile from CV",
        "requirements": [
            "Return strict JSON only.",
            "Preserve original language where possible.",
            "skills/experience/education/languages must be concise and deduplicated.",
            "recommended_queries must be concrete LinkedIn search phrases.",
            "Infer target roles from full CV, prioritizing all major tracks in experience and education.",
            "If academic/teaching or human resources experience exists, include them in target_roles or secondary_roles.",
            "target_roles and secondary_roles must be only job titles (2-6 words), never achievements, metrics, or full sentences.",
            "Use evidence from all CV sections, not only the profile paragraph.",
            "Always include at least 3 role titles when enough evidence exists.",
        ],
        "json_schema": {
            "highlights": ["string"],
            "skills": ["string"],
            "experience": ["string"],
            "education": ["string"],
            "languages": ["string"],
            "target_roles": ["string"],
            "secondary_roles": ["string"],
            "seniority": "junior|mid|senior|lead|unknown",
            "industries": ["string"],
            "strengths": ["string"],
            "skill_gaps": ["string"],
            "recommended_queries": ["string"],
        },
        "current_summary": current_summary,
        "cv_text_redacted": cv_text,
    }
    return json.dumps(payload, ensure_ascii=True)


def build_job_prompt(
    *,
    prompt_version: str,
    profile_summary: dict,
    profile_analysis: dict,
    job_payload: dict,
    deterministic_score: float,
) -> str:
    payload = {
        "prompt_version": prompt_version,
        "task": "Categorize and score job fit for candidate",
        "requirements": [
            "Return strict JSON only.",
            "Score llm_fit_score from 0 to 100.",
            "Focus on skills, education, experience and role seniority alignment.",
            "Use concise fit_reasons and gap_notes.",
        ],
        "json_schema": {
            "job_category": "string|null",
            "job_subcategory": "string|null",
            "llm_fit_score": "number",
            "fit_reasons": ["string"],
            "gap_notes": ["string"],
            "role_alignment": ["string"],
        },
        "candidate_profile_summary": profile_summary,
        "candidate_analysis": profile_analysis,
        "job": job_payload,
        "deterministic_score": deterministic_score,
    }
    return json.dumps(payload, ensure_ascii=True)


def build_repair_prompt(raw_output: str) -> str:
    payload = {
        "task": "Repair invalid JSON",
        "requirements": [
            "Return JSON only.",
            "Do not add commentary.",
            "Keep keys and structure inferred from the original response.",
        ],
        "input": raw_output,
    }
    return json.dumps(payload, ensure_ascii=True)
