from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CVSummary(BaseModel):
    highlights: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class CVAnalysisOut(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    secondary_roles: list[str] = Field(default_factory=list)
    seniority: str = "unknown"
    industries: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    recommended_queries: list[str] = Field(default_factory=list)
    llm_status: str = "fallback"
    llm_error: str | None = None


class CVUploadOut(BaseModel):
    cv_id: str
    session_id: str | None = None
    text_chars: int
    summary: CVSummary
    analysis: CVAnalysisOut
    created_at: datetime


class CVSummaryOut(BaseModel):
    cv_id: str
    summary: CVSummary
    analysis: CVAnalysisOut
    confirmed_at: datetime | None = None
    updated_at: datetime


class MarketRoleOut(BaseModel):
    role: str
    demand_score: float
    source: str
    rationale: str | None = None


class CVSearchStrategyOut(BaseModel):
    cv_id: str
    role_focus: list[str] = Field(default_factory=list)
    recommended_queries: list[str] = Field(default_factory=list)
    market_roles: list[MarketRoleOut] = Field(default_factory=list)


class CVSummaryUpdateIn(BaseModel):
    summary: CVSummary


class SearchCreateIn(BaseModel):
    cv_id: str
    country: str | None = None
    city: str | None = None
    time_window_hours: Literal[1, 3, 8, 24, 72, 168, 720] = 24
    keywords: list[str] = Field(default_factory=list)


class SearchUpdateIn(BaseModel):
    country: str | None = None
    city: str | None = None
    time_window_hours: Literal[1, 3, 8, 24, 72, 168, 720] | None = None
    keywords: list[str] | None = None
    active: bool | None = None


class SearchConfigOut(BaseModel):
    search_id: str
    cv_id: str
    country: str | None = None
    city: str | None = None
    time_window_hours: int
    keywords: list[str] = Field(default_factory=list)
    active: bool


class SearchRunOut(BaseModel):
    run_id: str
    search_id: str
    status: str
    total_found: int
    new_found: int
    started_at: datetime
    finished_at: datetime | None = None


class SearchResultOut(BaseModel):
    result_id: str
    job_id: str
    title: str
    company: str | None = None
    description: str
    location: str | None = None
    modality: str | None = None
    easy_apply: bool
    applicant_count: int = 0
    job_category: str | None = None
    job_subcategory: str | None = None
    match_percent: float
    llm_fit_score: float = 0.0
    final_score: float = 0.0
    match_breakdown: dict = Field(default_factory=dict)
    fit_reasons: list[str] = Field(default_factory=list)
    gap_notes: list[str] = Field(default_factory=list)
    role_alignment: list[str] = Field(default_factory=list)
    llm_status: str = "fallback"
    job_url: str
    posted_at: datetime | None = None
    posted_age_hours: float | None = None
    discovered_at: datetime
    is_new: bool
    checked: bool


class SearchResultsOut(BaseModel):
    search_id: str
    total: int
    page: int = 1
    page_size: int = 50
    total_pages: int = 0
    has_prev: bool = False
    has_next: bool = False
    items: list[SearchResultOut]


class SearchCreateOut(BaseModel):
    search_id: str
    run: SearchRunOut
    results: SearchResultsOut


class CheckUpdateIn(BaseModel):
    checked: bool


class SchedulerStatusOut(BaseModel):
    is_running: bool
    interval_minutes: int
    last_tick_at: datetime | None


class SchedulerStartIn(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=1, le=720)


class SearchFacetsOut(BaseModel):
    categories: dict[str, int] = Field(default_factory=dict)
    subcategories: dict[str, int] = Field(default_factory=dict)
    modalities: dict[str, int] = Field(default_factory=dict)
    locations: dict[str, int] = Field(default_factory=dict)
    posted_buckets: dict[str, int] = Field(default_factory=dict)


class SessionOut(BaseModel):
    session_id: str
    cv_id: str
    active_search_id: str | None = None
    ui_state: dict = Field(default_factory=dict)
    status: str
    created_at: datetime
    last_seen_at: datetime


class SessionCurrentOut(BaseModel):
    session: SessionOut | None = None


class SessionResumeIn(BaseModel):
    session_id: str
    active_search_id: str | None = None
    ui_state: dict | None = None


class SessionStateUpdateIn(BaseModel):
    session_id: str
    active_search_id: str | None = None
    ui_state: dict | None = None


class SessionCloseIn(BaseModel):
    session_id: str
