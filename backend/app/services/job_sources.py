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
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "laborum_public": SourceSpec(
        source_id="laborum_public",
        label="Laborum",
        description="Portal privado de empleo con foco en LatAm.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "computrabajo_public": SourceSpec(
        source_id="computrabajo_public",
        label="Computrabajo",
        description="Portal de empleo regional con alta cobertura en LatAm.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "trabajosdiarios_public": SourceSpec(
        source_id="trabajosdiarios_public",
        label="TrabajosDiarios",
        description="Bolsa de empleo privada orientada a avisos locales.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "indeed_public": SourceSpec(
        source_id="indeed_public",
        label="Indeed",
        description="Agregador global de empleo.",
        enabled=False,
        status_note="No habilitado: acceso automatizado restringido sin integración oficial.",
    ),
    "glassdoor_public": SourceSpec(
        source_id="glassdoor_public",
        label="Glassdoor",
        description="Portal global de empleo y reputación de empresas.",
        enabled=False,
        status_note="Pendiente: requiere integración aprobada y revisión de términos de uso.",
    ),
    "flexjobs_public": SourceSpec(
        source_id="flexjobs_public",
        label="FlexJobs",
        description="Portal de empleos remotos y flexibles.",
        enabled=False,
        status_note="Pendiente: requiere integración aprobada y revisión de términos de uso.",
    ),
    "weworkremotely_public": SourceSpec(
        source_id="weworkremotely_public",
        label="We Work Remotely",
        description="Portal internacional de empleo remoto.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "remoteco_public": SourceSpec(
        source_id="remoteco_public",
        label="Remote.co",
        description="Portal curado de empleos remotos.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
    "dailyremote_public": SourceSpec(
        source_id="dailyremote_public",
        label="DailyRemote",
        description="Agregador de ofertas remotas.",
        enabled=False,
        status_note="Pendiente: requiere conector dedicado y revisión de términos de uso.",
    ),
}


def list_allowed_sources() -> list[SourceSpec]:
    ordered = [
        "linkedin_public",
        "bne_public",
        "empleos_publicos_public",
        "trabajando_public",
        "laborum_public",
        "computrabajo_public",
        "trabajosdiarios_public",
        "indeed_public",
        "glassdoor_public",
        "flexjobs_public",
        "weworkremotely_public",
        "remoteco_public",
        "dailyremote_public",
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
