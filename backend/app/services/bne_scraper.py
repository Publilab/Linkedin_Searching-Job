from __future__ import annotations

import html
import random
import re
import time
from datetime import datetime, timedelta

import httpx

from app.services.linkedin_scraper import (
    TRANSIENT_STATUS_CODES,
    detect_easy_apply,
    detect_modality,
    hash_url,
    normalize_job_url,
)

BNE_SEARCH_ENDPOINT = "http://www.bne.cl/data/ofertas/buscarListas"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")


def scrape_jobs(
    keywords: str,
    *,
    city: str | None = None,
    country: str | None = None,
    time_window_hours: int = 24,
    max_results: int = 50,
    timeout_seconds: float = 10.0,
) -> list[dict]:
    query = " ".join((keywords or "").split()).strip()
    if not query:
        return []

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    per_page = max(1, min(25, int(max_results)))
    page = 1
    seen_hashes: set[str] = set()
    results: list[dict] = []

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        while len(results) < max_results:
            payload = _fetch_page(client, query, page, per_page)
            if not payload:
                break

            page_data = payload.get("paginaOfertas") or {}
            raw_results = page_data.get("resultados") or []
            if not raw_results:
                break

            for raw in raw_results:
                item = _normalize_item(raw, city=city, country=country, time_window_hours=time_window_hours)
                if not item:
                    continue

                url_hash = item["canonical_url_hash"]
                if url_hash in seen_hashes:
                    continue

                seen_hashes.add(url_hash)
                results.append(item)
                if len(results) >= max_results:
                    break

            num_pages = int(page_data.get("numPaginasTotal") or page)
            if page >= num_pages:
                break
            page += 1

    return results


def _fetch_page(client: httpx.Client, keywords: str, page: int, per_page: int) -> dict | None:
    params = {
        "mostrar": "empleo",
        "textoLibre": keywords,
        "numPaginaRecuperar": str(page),
        "numResultadosPorPagina": str(per_page),
        "clasificarYPaginar": "true",
    }

    for attempt in range(1, 4):
        try:
            response = client.get(BNE_SEARCH_ENDPOINT, params=params)
            if response.status_code in TRANSIENT_STATUS_CODES:
                raise httpx.HTTPStatusError(
                    f"transient status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt >= 3:
                return None
            delay = min(2.5, 0.35 * (2 ** (attempt - 1)))
            time.sleep(delay + random.uniform(0.0, 0.2))
    return None


def _normalize_item(
    raw: dict,
    *,
    city: str | None,
    country: str | None,
    time_window_hours: int,
) -> dict | None:
    external_job_id = _clean_text(raw.get("codigo") or raw.get("id"))
    if not external_job_id:
        return None

    canonical_url = normalize_job_url(f"https://www.bne.cl/oferta/{external_job_id}")
    if not canonical_url:
        return None

    title = _clean_text(raw.get("titulo")) or "Untitled role"
    description = _clean_text(raw.get("descripcion")) or title
    company = _clean_text(raw.get("empresa")) or None

    region = _clean_text(raw.get("region"))
    comuna = _clean_text(raw.get("comuna"))
    location = ", ".join([part for part in [comuna, region] if part]) or None
    if not _location_matches(location, city, country):
        return None

    posted_at = _parse_posted_at(raw.get("fecha"))
    if posted_at and not _within_time_window(posted_at, time_window_hours):
        return None

    hint_blob = " ".join(
        [
            title,
            description,
            _clean_text(raw.get("tipoJornada")),
            _clean_text(raw.get("tipoContrato")),
        ]
    )

    return {
        "source": "bne_public",
        "external_job_id": external_job_id,
        "canonical_url": canonical_url,
        "canonical_url_hash": hash_url(canonical_url),
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "modality": detect_modality(hint_blob),
        "easy_apply": detect_easy_apply(hint_blob),
        "applicant_count": 0,
        "applicant_count_raw": None,
        "posted_at": posted_at,
    }


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    raw = str(value)
    raw = _TAG_RE.sub(" ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _parse_posted_at(raw_value: object) -> datetime | None:
    text = _clean_text(raw_value)
    if not text:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _within_time_window(posted_at: datetime, time_window_hours: int) -> bool:
    return posted_at >= (datetime.utcnow() - timedelta(hours=max(1, int(time_window_hours))))


def _location_matches(location: str | None, city: str | None, country: str | None) -> bool:
    if not city and not country:
        return True

    loc = (location or "").lower()
    city_ok = True
    country_ok = True
    if city:
        city_ok = city.lower().strip() in loc
    if country:
        normalized_country = country.lower().strip()
        if normalized_country in {"chile", "cl"}:
            country_ok = True
        else:
            country_ok = normalized_country in loc
    return city_ok and country_ok
