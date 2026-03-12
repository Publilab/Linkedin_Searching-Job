from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+\b", re.IGNORECASE)
_NAME_LINE_RE = re.compile(r"^[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'`.-]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'`.-]+){1,3}$")


def redact_pii(text: str) -> str:
    if not text:
        return ""

    redacted = _EMAIL_RE.sub("[EMAIL]", text)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    redacted = _URL_RE.sub("[URL]", redacted)

    lines = redacted.splitlines()
    for idx, line in enumerate(lines[:3]):
        cleaned = " ".join(line.strip().split())
        if cleaned and _NAME_LINE_RE.match(cleaned):
            lines[idx] = "[NAME]"

    return "\n".join(lines)
