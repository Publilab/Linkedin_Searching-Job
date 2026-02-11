from __future__ import annotations

from dataclasses import dataclass

from app.services import bne_scraper, empleos_publicos_scraper
from app.services.linkedin_scraper import scrape_jobs as scrape_linkedin_jobs

DEFAULT_SOURCE = "linkedin_public"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    label: str
    description: str
    enabled: bool = True
    status_note: str | None = None


_SOURCES: dict[str, SourceSpec] = {
    "linkedin_public": SourceSpec(
        source_id="linkedin_public",
        label="LinkedIn Jobs (public)",
        description="LinkedIn Jobs guest/public pages (sin login).",
        enabled=True,
    ),
    "bne_public": SourceSpec(
        source_id="bne_public",
        label="BNE (Bolsa Nacional de Empleo)",
        description="Portal público oficial de empleo en Chile.",
        enabled=True,
    ),
    "empleos_publicos_public": SourceSpec(
        source_id="empleos_publicos_public",
        label="Empleos Públicos (Servicio Civil)",
        description="Portal oficial de convocatorias públicas en Chile.",
        enabled=True,
    ),
    "trabajando_public": SourceSpec(
        source_id="trabajando_public",
        label="Trabajando.com",
        description="Portal privado de empleo.",
        enabled=False,
        status_note="No disponible por ahora: requiere integración oficial/API.",
    ),
    "indeed_public": SourceSpec(
        source_id="indeed_public",
        label="Indeed",
        description="Agregador global de empleo.",
        enabled=False,
        status_note="No disponible por ahora: acceso automatizado bloqueado sin integración oficial.",
    ),
}


def list_allowed_sources() -> list[SourceSpec]:
    ordered = [
        "linkedin_public",
        "bne_public",
        "empleos_publicos_public",
        "trabajando_public",
        "indeed_public",
    ]
    return [_SOURCES[source_id] for source_id in ordered if source_id in _SOURCES]


def normalize_sources(sources: list[str] | None) -> list[str]:
    requested = [str(source).strip() for source in (sources or []) if str(source).strip()]
    normalized: list[str] = []
    seen: set[str] = set()

    for source in requested:
        spec = _SOURCES.get(source)
        if not spec or not spec.enabled:
            continue
        if source in seen:
            continue
        seen.add(source)
        normalized.append(source)

    if not normalized:
        normalized.append(DEFAULT_SOURCE)
    return normalized


def fetch_jobs(
    *,
    source_id: str,
    keywords: str,
    location: str,
    city: str | None,
    country: str | None,
    time_window_hours: int,
    max_results: int = 30,
) -> list[dict]:
    if source_id == "linkedin_public":
        return scrape_linkedin_jobs(
            keywords=keywords,
            location=location,
            time_window_hours=time_window_hours,
            max_results=max_results,
        )
    if source_id == "bne_public":
        return bne_scraper.scrape_jobs(
            keywords=keywords,
            city=city,
            country=country,
            time_window_hours=time_window_hours,
            max_results=max_results,
        )
    if source_id == "empleos_publicos_public":
        return empleos_publicos_scraper.scrape_jobs(
            keywords=keywords,
            city=city,
            country=country,
            time_window_hours=time_window_hours,
            max_results=max_results,
        )
    return []
