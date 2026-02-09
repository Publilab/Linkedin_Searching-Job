from __future__ import annotations

import re


SKILL_TOKENS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "react",
    "node",
    "aws",
    "azure",
    "docker",
    "kubernetes",
    "power bi",
    "tableau",
    "excel",
    "fastapi",
    "django",
}


def compute_match(profile: dict, job: dict) -> tuple[float, dict]:
    profile_skills = _tokenize(profile.get("skills", []))
    profile_experience = _tokenize(profile.get("experience", []))
    profile_education = _tokenize(profile.get("education", []))

    job_title_desc = f"{job.get('title', '')} {job.get('description', '')}".lower()
    job_tokens = _tokenize([job_title_desc])
    job_skill_tokens = {token for token in SKILL_TOKENS if token in job_title_desc}

    skill_score = _ratio(len(profile_skills & job_skill_tokens), max(len(job_skill_tokens), 1))
    experience_score = _ratio(len(profile_experience & job_tokens), max(len(profile_experience), 1))
    education_score = _ratio(len(profile_education & job_tokens), max(len(profile_education), 1))

    weighted = (0.5 * skill_score) + (0.3 * experience_score) + (0.2 * education_score)
    match_percent = round(weighted * 100, 2)

    breakdown = {
        "skills": round(skill_score * 100, 2),
        "experience": round(experience_score * 100, 2),
        "education": round(education_score * 100, 2),
        "matched_skills": sorted(profile_skills & job_skill_tokens),
    }

    return match_percent, breakdown


def _tokenize(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\+\.#-]{2,}", value.lower()):
            tokens.add(token)
    return tokens


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return min(max(num / den, 0.0), 1.0)
