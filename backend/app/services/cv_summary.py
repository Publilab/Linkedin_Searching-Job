from __future__ import annotations

import re

KNOWN_SKILLS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "postgresql",
    "mysql",
    "sqlite",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "react",
    "next.js",
    "nextjs",
    "node",
    "fastapi",
    "django",
    "flask",
    "pandas",
    "numpy",
    "excel",
    "power bi",
    "tableau",
    "git",
    "linux",
    "scrum",
    "gestion publica",
    "administracion publica",
    "gestion de proyectos",
    "analisis de datos",
    "compras publicas",
    "licitaciones",
}

ROLE_HINTS = {
    "developer",
    "engineer",
    "analyst",
    "scientist",
    "manager",
    "consultant",
    "architect",
    "designer",
    "lead",
    "intern",
    "administrador",
    "coordinador",
    "especialista",
    "jefe",
    "director",
    "asistente",
    "encargado",
    "publico",
    "publica",
    "academico",
    "académico",
    "academica",
    "académica",
    "docente",
    "profesor",
    "profesora",
    "instructor",
    "relator",
    "rrhh",
    "recursos humanos",
    "talento humano",
    "human resources",
    "people",
}

EDU_HINTS = {
    "university",
    "college",
    "bachelor",
    "master",
    "phd",
    "degree",
    "ingenier",
    "licenci",
    "bootcamp",
    "certification",
    "educacion",
    "educación",
    "formacion",
    "formación",
    "academica",
    "académica",
    "tecnico",
    "técnico",
    "diplomado",
    "curso",
    "capacitacion",
    "capacitación",
    "administrador publico",
    "administrador público",
}

LANG_HINTS = {
    "english": "English",
    "spanish": "Spanish",
    "espanol": "Spanish",
    "español": "Spanish",
    "portuguese": "Portuguese",
    "french": "French",
    "german": "German",
    "italian": "Italian",
    "ingles": "English",
    "inglés": "English",
}

SECTION_KEYWORDS = {
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "experiencia",
        "experiencia laboral",
        "trayectoria",
        "historial laboral",
    },
    "education": {
        "education",
        "academic background",
        "formacion",
        "formación",
        "educacion",
        "educación",
        "formacion academica",
        "formación académica",
        "estudios",
    },
    "skills": {
        "skills",
        "technical skills",
        "habilidades",
        "competencias",
        "conocimientos",
        "stack",
    },
    "languages": {
        "languages",
        "idiomas",
        "lenguas",
    },
    "training": {
        "certifications",
        "certification",
        "courses",
        "course",
        "capacitaciones",
        "capacitacion",
        "capacitación",
        "cursos",
        "diplomados",
        "diplomado",
        "seminarios",
    },
    "profile": {
        "profile",
        "professional profile",
        "resumen",
        "perfil",
        "perfil profesional",
        "about me",
    },
}


def summarize_cv_text(text: str) -> dict:
    cleaned_lines = _clean_lines(text)
    raw = "\n".join(cleaned_lines)
    lower = raw.lower()

    sections = _split_sections(cleaned_lines)

    skills = _extract_skills(lower, sections)
    experience = _extract_experience(cleaned_lines, sections)
    education = _extract_education(cleaned_lines, sections)
    languages = _extract_languages(lower, sections)
    highlights = _build_highlights(cleaned_lines, sections, experience, education)

    return {
        "highlights": highlights,
        "skills": skills,
        "experience": experience,
        "education": education,
        "languages": languages,
    }


def _clean_lines(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        cleaned = " ".join(line.strip(" -\t\u2022\u00b7").split())
        if cleaned:
            out.append(cleaned)
    return out


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections = {
        "profile": [],
        "experience": [],
        "education": [],
        "skills": [],
        "languages": [],
        "training": [],
        "general": [],
    }

    active = "general"
    for line in lines:
        section = _detect_section(line)
        if section:
            active = section
            continue
        sections.setdefault(active, []).append(line)

    return sections


def _detect_section(line: str) -> str | None:
    normalized = _normalize_for_section(line)
    if not normalized:
        return None

    for section, keywords in SECTION_KEYWORDS.items():
        for keyword in keywords:
            if normalized == keyword or normalized.startswith(f"{keyword} "):
                return section
            if normalized == f"{keyword}:":
                return section
    return None


def _normalize_for_section(line: str) -> str:
    lower = line.lower().strip()
    lower = re.sub(r"[:\-]+$", "", lower)
    lower = re.sub(r"\s+", " ", lower)
    return lower


def _extract_skills(text_lower: str, sections: dict[str, list[str]]) -> list[str]:
    found: list[str] = []

    for skill in sorted(KNOWN_SKILLS):
        pattern = rf"\b{re.escape(skill)}\b"
        if re.search(pattern, text_lower):
            found.append(skill)

    section_text = " ; ".join(sections.get("skills", []) + sections.get("training", []))
    for token in _split_skill_tokens(section_text):
        if len(token) >= 2:
            found.append(token)

    return _dedupe(found)[:45]


def _split_skill_tokens(text: str) -> list[str]:
    if not text:
        return []
    chunks = re.split(r"[,;|/]", text)
    out: list[str] = []
    for chunk in chunks:
        cleaned = " ".join(chunk.strip().split())
        cleaned = re.sub(r"^(habilidades|competencias|skills?)\s*:?\s*", "", cleaned, flags=re.IGNORECASE)
        if cleaned:
            out.append(cleaned.lower())
    return out


def _extract_experience(lines: list[str], sections: dict[str, list[str]]) -> list[str]:
    target_lines = sections.get("experience", []) or lines

    out: list[str] = []
    for line in target_lines:
        low = line.lower()
        if any(role in low for role in ROLE_HINTS) and len(line) <= 220:
            out.append(line)
            continue
        if _looks_like_date_range(low) and len(line) <= 220:
            out.append(line)

    if len(out) < 4:
        for line in lines:
            low = line.lower()
            if _looks_like_date_range(low) and len(line) <= 220:
                out.append(line)

    return _dedupe(out)[:20]


def _extract_education(lines: list[str], sections: dict[str, list[str]]) -> list[str]:
    target_lines = (sections.get("education", []) or []) + (sections.get("training", []) or [])
    if not target_lines:
        target_lines = lines

    out: list[str] = []
    for line in target_lines:
        low = line.lower()
        if any(h in low for h in EDU_HINTS) and len(line) <= 240:
            out.append(line)
            continue
        if "administrador publico" in low or "administrador público" in low:
            out.append(line)

    return _dedupe(out)[:18]


def _extract_languages(text_lower: str, sections: dict[str, list[str]]) -> list[str]:
    out: list[str] = []

    lang_text = text_lower + " " + " ".join(sections.get("languages", [])).lower()
    for token, display in LANG_HINTS.items():
        if re.search(rf"\b{re.escape(token)}\b", lang_text):
            out.append(display)
    return _dedupe(out)


def _build_highlights(
    lines: list[str],
    sections: dict[str, list[str]],
    experience: list[str],
    education: list[str],
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(sections.get("profile", [])[:4])
    candidates.extend(sections.get("general", [])[:4])
    candidates.extend(experience[:4])
    candidates.extend(education[:3])

    if not candidates:
        candidates = lines[:10]

    return _dedupe(candidates)[:14]


def _looks_like_date_range(text: str) -> bool:
    if re.search(r"\b(19|20)\d{2}\b", text):
        return True
    if re.search(r"\b(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic|jan|apr|aug|dec)\b", text):
        return True
    if re.search(r"\b(?:actual|present|hoy)\b", text):
        return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out
