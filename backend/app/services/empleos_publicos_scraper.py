from __future__ import annotations

import hashlib
import html
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.linkedin_scraper import detect_modality, hash_url, normalize_job_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DATA_URLS = [
    "https://www.empleospublicos.cl/data/convocatorias2_nueva.txt",
    "https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt",
]

_CACHE_TTL_SECONDS = 600
_CACHE: dict[str, object] = {
    "loaded_at": None,
    "items": [],
}


def scrape_jobs(
    keywords: str,
    *,
    city: str | None = None,
    country: str | None = None,
    time_window_hours: int = 24,
    max_results: int = 50,
    timeout_seconds: float = 12.0,
) -> list[dict]:
    query = " ".join((keywords or "").split()).strip()
    if not query:
        return []

    raw_items = _load_dataset(timeout_seconds=timeout_seconds)
    if not raw_items:
        return []

    tokens = _query_tokens(query)
    now = datetime.utcnow()
    seen_hashes: set[str] = set()
    results: list[dict] = []

    for raw in raw_items:
        normalized = _normalize_item(raw)
        if not normalized:
            continue

        if not _matches_keywords(normalized, tokens):
            continue
        if not _matches_location(normalized.get("location"), city, country):
            continue

        posted_at = normalized.get("posted_at")
        if isinstance(posted_at, datetime):
            min_dt = now - timedelta(hours=max(1, int(time_window_hours)))
            if posted_at < min_dt:
                continue

        canonical_hash = str(normalized.get("canonical_url_hash") or "").strip()
        if not canonical_hash or canonical_hash in seen_hashes:
            continue
        seen_hashes.add(canonical_hash)

        results.append(normalized)
        if len(results) >= max_results:
            break

    return results


def _load_dataset(*, timeout_seconds: float) -> list[dict]:
    now = datetime.utcnow()
    loaded_at = _CACHE.get("loaded_at")
    cached_items = _CACHE.get("items")

    if isinstance(loaded_at, datetime) and isinstance(cached_items, list):
        if (now - loaded_at).total_seconds() <= _CACHE_TTL_SECONDS:
            return cached_items

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
    }

    out: list[dict] = []
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        for url in DATA_URLS:
            payload = _fetch_json_payload(client, url)
            if isinstance(payload, list):
                out.extend([item for item in payload if isinstance(item, dict)])

    _CACHE["loaded_at"] = now
    _CACHE["items"] = out
    return out


def _fetch_json_payload(client: httpx.Client, url: str) -> object:
    for attempt in range(1, 4):
        try:
            response = client.get(url)
            response.raise_for_status()
            text = response.text.lstrip("\ufeff").strip()
            if not text:
                return []
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt >= 3:
                return []
            delay = min(2.4, 0.4 * (2 ** (attempt - 1)))
            time.sleep(delay + random.uniform(0.0, 0.2))
    return []


def _normalize_item(raw: dict) -> dict | None:
    url = _clean(raw.get("url"))
    canonical_url = normalize_job_url(url)
    if not canonical_url:
        return None

    external_job_id = _extract_external_id(canonical_url)
    if not external_job_id:
        external_job_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]

    title = _clean(raw.get("Cargo")) or "Untitled role"
    institution = _clean(raw.get("Institución / Entidad"))
    ministry = _clean(raw.get("Ministerio"))
    area = _clean(raw.get("Área de Trabajo"))
    vacancy_type = _clean(raw.get("Tipo de Vacante"))
    region = _clean(raw.get("Región"))
    city = _clean(raw.get("Ciudad"))
    location = ", ".join([part for part in [city, region] if part]) or region or city or None

    description_parts = [part for part in [institution, ministry, area, vacancy_type] if part]
    description = " | ".join(description_parts) if description_parts else title

    postulation_type = _clean(raw.get("Tipo postulacion"))
    easy_apply = "en linea" in postulation_type.lower() or "en línea" in postulation_type.lower()
    modality_hint = " ".join([title, description, postulation_type])

    return {
        "source": "empleos_publicos_public",
        "external_job_id": external_job_id,
        "canonical_url": canonical_url,
        "canonical_url_hash": hash_url(canonical_url),
        "title": title,
        "company": institution or ministry or "Empleos Públicos",
        "location": location,
        "description": description,
        "modality": detect_modality(modality_hint),
        "easy_apply": easy_apply,
        "applicant_count": 0,
        "applicant_count_raw": None,
        "posted_at": _parse_date(raw.get("Fecha Inicio")),
    }


def _extract_external_id(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("i", "id", "job", "oferta"):
        value = query.get(key)
        if value and value[0]:
            return value[0]

    match = re.search(r"/(?:trabajo|oferta)[^/]*?/(\d+)", parsed.path)
    if match:
        return match.group(1)
    return None


def _parse_date(value: object) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d/%m/%y %H:%M:%S", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _matches_keywords(item: dict, tokens: list[str]) -> bool:
    if not tokens:
        return True

    corpus = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("company") or ""),
            str(item.get("description") or ""),
            str(item.get("location") or ""),
        ]
    ).lower()

    return any(token in corpus for token in tokens)


def _query_tokens(query: str) -> list[str]:
    tokens = re.split(r"\s+", query.lower())
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        clean = re.sub(r"[^a-z0-9áéíóúñü]+", "", token, flags=re.IGNORECASE)
        if len(clean) < 3:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _matches_location(location: str | None, city: str | None, country: str | None) -> bool:
    if not city and not country:
        return True

    low_location = (location or "").lower()
    city_ok = True
    country_ok = True
    if city:
        city_ok = city.lower().strip() in low_location
    if country:
        normalized_country = country.lower().strip()
        if normalized_country in {"chile", "cl"}:
            country_ok = True
        else:
            country_ok = normalized_country in low_location
    return city_ok and country_ok


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
