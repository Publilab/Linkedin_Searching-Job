from __future__ import annotations

import hashlib
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def normalize_job_url(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate.lstrip('/')}"

    parsed = urlsplit(candidate)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def extract_job_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/jobs/view/(\d+)", url)
    if match:
        return match.group(1)
    return None


def parse_applicant_count(raw_text: str | None) -> tuple[int, str | None]:
    if raw_text is None:
        return 0, None
    cleaned = raw_text.strip()
    if not cleaned:
        return 0, None

    keyword_pattern = r"(?:applicants?|postulantes?|solicitantes?|candidatos?)"
    match = re.search(
        rf"(?P<count>\d[\d\s\.,kK]*)\s*\+?\s*{keyword_pattern}",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"{keyword_pattern}\D*(?P<count>\d[\d\s\.,kK]*)",
            cleaned,
            re.IGNORECASE,
        )
    if not match:
        match = re.search(
            r"(?:among\s+first|first|primeros?|entre\s+los\s+primeros)\D*(?P<count>\d[\d\s\.,kK]*)",
            cleaned,
            re.IGNORECASE,
        )
    if match:
        return _parse_count_token(match.group("count")), cleaned

    # Accept plain numeric sources only (avoid extracting random numbers from full descriptions).
    if re.fullmatch(r"\d[\d\s\.,kK]*\+?", cleaned):
        return _parse_count_token(cleaned), cleaned
    return 0, None


def _parse_count_token(value: str) -> int:
    token = (value or "").strip().lower().replace(" ", "").rstrip("+")
    if not token:
        return 0
    if token.endswith("k"):
        base = token[:-1].replace(",", ".")
        try:
            return int(float(base) * 1000)
        except ValueError:
            pass
    digits = re.sub(r"\D", "", token)
    return int(digits) if digits else 0


def detect_modality(text: str) -> str | None:
    low = text.lower()
    if any(k in low for k in ["remote", "remoto"]):
        return "remote"
    if any(k in low for k in ["hybrid", "hibrid", "híbrido", "hibrido"]):
        return "hybrid"
    if any(k in low for k in ["on-site", "onsite", "presencial"]):
        return "onsite"
    return None


def detect_easy_apply(text: str) -> bool:
    low = text.lower()
    return "easy apply" in low or "solicitud sencilla" in low


def parse_relative_posted_at(raw_text: str | None) -> datetime | None:
    if not raw_text:
        return None
    low = raw_text.lower().strip()
    match = re.search(r"(\d+)\s*(minute|hour|day|week|mes|month|semana|hora|minuto|dia)", low)
    if not match:
        return None
    qty = int(match.group(1))
    unit = match.group(2)

    now = datetime.utcnow()
    if unit.startswith("minute") or unit.startswith("minuto"):
        return now - timedelta(minutes=qty)
    if unit.startswith("hour") or unit.startswith("hora"):
        return now - timedelta(hours=qty)
    if unit.startswith("day") or unit.startswith("dia"):
        return now - timedelta(days=qty)
    if unit.startswith("week") or unit.startswith("semana"):
        return now - timedelta(weeks=qty)
    if unit.startswith("month") or unit.startswith("mes"):
        return now - timedelta(days=30 * qty)
    return None


def time_window_to_seconds(hours: int) -> int:
    return int(hours * 3600)


def build_search_url(keywords: str, location: str, hours: int, start: int = 0) -> str:
    params = {
        "keywords": keywords,
        "location": location,
        "start": str(start),
        "f_TPR": f"r{time_window_to_seconds(hours)}",
        "sortBy": "DD",
    }
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)


def request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 0.4,
    max_delay_seconds: float = 4.0,
) -> httpx.Response | None:
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url)
            if response.status_code in TRANSIENT_STATUS_CODES:
                raise httpx.HTTPStatusError(
                    f"transient status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code not in TRANSIENT_STATUS_CODES:
                return None
            if attempt >= max_attempts:
                return None
        except httpx.HTTPError:
            if attempt >= max_attempts:
                return None

        delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, delay * 0.25)
        time.sleep(delay + jitter)

    return None


def scrape_jobs(
    keywords: str,
    location: str,
    time_window_hours: int,
    *,
    max_results: int = 50,
    timeout_seconds: float = 10.0,
) -> list[dict]:
    if not keywords.strip():
        return []

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    seen_hashes: set[str] = set()
    results: list[dict] = []

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        for start in range(0, max_results, 25):
            search_url = build_search_url(keywords, location, time_window_hours, start=start)
            response = request_with_retry(client, search_url)
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.select("li")
            if not cards:
                break

            for card in cards:
                if len(results) >= max_results:
                    break

                anchor = card.select_one("a.base-card__full-link") or card.select_one("a")
                if not anchor:
                    continue
                raw_url = anchor.get("href")
                canonical = normalize_job_url(raw_url)
                if not canonical:
                    continue
                canonical_hash = hash_url(canonical)
                if canonical_hash in seen_hashes:
                    continue
                seen_hashes.add(canonical_hash)

                title = card.select_one("h3") or card.select_one(".base-search-card__title")
                company = card.select_one("h4") or card.select_one(".base-search-card__subtitle")
                place = card.select_one(".job-search-card__location")
                posted = card.select_one("time")

                title_txt = title.get_text(" ", strip=True) if title else ""
                company_txt = company.get_text(" ", strip=True) if company else None
                location_txt = place.get_text(" ", strip=True) if place else None
                posted_label = posted.get_text(" ", strip=True) if posted else None

                external_id = extract_job_id(canonical)
                detail_text = ""
                if external_id:
                    detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{external_id}"
                    detail_response = request_with_retry(
                        client,
                        detail_url,
                        max_attempts=3,
                        base_delay_seconds=0.25,
                        max_delay_seconds=1.5,
                    )
                    if detail_response is not None:
                        detail_soup = BeautifulSoup(detail_response.text, "lxml")
                        detail_text = detail_soup.get_text(" ", strip=True)

                applicant_candidates = [
                    detail_text,
                    card.get_text(" ", strip=True),
                ]
                applicant_count = 0
                applicant_raw: str | None = None
                for source in applicant_candidates:
                    count, raw = parse_applicant_count(source)
                    if raw and applicant_raw is None:
                        applicant_raw = raw
                    if count > 0:
                        applicant_count = count
                        applicant_raw = raw
                        break

                modality = detect_modality((detail_text or "") + " " + (location_txt or ""))
                easy_apply = detect_easy_apply(detail_text)

                results.append(
                    {
                        "source": "linkedin_public",
                        "external_job_id": external_id,
                        "canonical_url": canonical,
                        "canonical_url_hash": canonical_hash,
                        "title": title_txt or "Untitled role",
                        "company": company_txt,
                        "location": location_txt,
                        "description": detail_text or title_txt,
                        "modality": modality,
                        "easy_apply": easy_apply,
                        "applicant_count": applicant_count,
                        "applicant_count_raw": applicant_raw,
                        "posted_at": parse_relative_posted_at(posted_label),
                    }
                )

            if len(results) >= max_results:
                break

    return results
