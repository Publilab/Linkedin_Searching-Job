from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CVDocument(Base):
    __tablename__ = "cv_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    profiles: Mapped[list[CandidateProfile]] = relationship(
        "CandidateProfile", back_populates="cv", cascade="all, delete-orphan"
    )
    searches: Mapped[list[SearchConfig]] = relationship(
        "SearchConfig", back_populates="cv", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[CVSession]] = relationship(
        "CVSession", back_populates="cv", cascade="all, delete-orphan"
    )


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False)

    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    skills_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    experience_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    education_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    languages_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    llm_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    llm_strategy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    profile_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    llm_prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_status: Mapped[str] = mapped_column(String(32), nullable=False, default="fallback")
    llm_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    cv: Mapped[CVDocument] = relationship("CVDocument", back_populates="profiles")

    __table_args__ = (UniqueConstraint("cv_id", name="uq_candidate_profiles_cv_id"),)


class SearchConfig(Base):
    __tablename__ = "search_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False)

    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    time_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    keywords_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    cv: Mapped[CVDocument] = relationship("CVDocument", back_populates="searches")
    runs: Mapped[list[SchedulerRun]] = relationship(
        "SchedulerRun", back_populates="search", cascade="all, delete-orphan"
    )
    results: Mapped[list[SearchResult]] = relationship(
        "SearchResult", back_populates="search", cascade="all, delete-orphan"
    )
    active_sessions: Mapped[list[CVSession]] = relationship("CVSession", back_populates="active_search")
    interactions: Mapped[list[Interaction]] = relationship(
        "Interaction", back_populates="search", cascade="all, delete-orphan"
    )
    llm_usage_logs: Mapped[list[LLMUsageLog]] = relationship(
        "LLMUsageLog", back_populates="search", cascade="all, delete-orphan"
    )


class CVSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False)
    active_search_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_configs.id", ondelete="SET NULL"), nullable=True
    )
    ui_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    cv: Mapped[CVDocument] = relationship("CVDocument", back_populates="sessions")
    active_search: Mapped[SearchConfig | None] = relationship("SearchConfig", back_populates="active_sessions")
    interactions: Mapped[list[Interaction]] = relationship(
        "Interaction", back_populates="session", cascade="all, delete-orphan"
    )
    llm_usage_logs: Mapped[list[LLMUsageLog]] = relationship(
        "LLMUsageLog", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_sessions_cv_last_seen", "cv_id", "last_seen_at"),
        Index("idx_sessions_status_last_seen", "status", "last_seen_at"),
    )


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    search_config_id: Mapped[str] = mapped_column(
        ForeignKey("search_configs.id", ondelete="CASCADE"), nullable=False
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    total_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    search: Mapped[SearchConfig] = relationship("SearchConfig", back_populates="runs")
    llm_usage_logs: Mapped[list[LLMUsageLog]] = relationship(
        "LLMUsageLog", back_populates="run", cascade="all, delete-orphan"
    )


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="linkedin_public")

    external_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    modality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    easy_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    applicant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applicant_count_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)

    job_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    job_subcategory: Mapped[str | None] = mapped_column(String(160), nullable=True)
    job_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    results: Mapped[list[SearchResult]] = relationship("SearchResult", back_populates="job")
    interactions: Mapped[list[Interaction]] = relationship(
        "Interaction", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="uq_job_postings_source_external_id"),
        Index("idx_job_postings_category", "job_category", "job_subcategory"),
    )


class SearchResult(Base):
    __tablename__ = "search_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    search_config_id: Mapped[str] = mapped_column(
        ForeignKey("search_configs.id", ondelete="CASCADE"), nullable=False
    )
    job_posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )

    match_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    match_breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    llm_fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fit_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gap_notes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    role_alignment_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    llm_status: Mapped[str] = mapped_column(String(32), nullable=False, default="fallback")
    llm_analysis_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    search: Mapped[SearchConfig] = relationship("SearchConfig", back_populates="results")
    job: Mapped[JobPosting] = relationship("JobPosting", back_populates="results")
    check: Mapped[ResultCheck | None] = relationship(
        "ResultCheck", back_populates="result", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("search_config_id", "job_posting_id", name="uq_search_result_job"),
        Index("idx_search_results_search_final_score", "search_config_id", "final_score"),
        Index("idx_search_results_search_discovered", "search_config_id", "discovered_at"),
    )


class ResultCheck(Base):
    __tablename__ = "result_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    search_result_id: Mapped[str] = mapped_column(
        ForeignKey("search_results.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    result: Mapped[SearchResult] = relationship("SearchResult", back_populates="check")


class SchedulerState(Base):
    __tablename__ = "scheduler_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    search_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_configs.id", ondelete="SET NULL"), nullable=True
    )
    job_posting_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    dwell_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    session: Mapped[CVSession | None] = relationship("CVSession", back_populates="interactions")
    search: Mapped[SearchConfig | None] = relationship("SearchConfig", back_populates="interactions")
    job: Mapped[JobPosting | None] = relationship("JobPosting", back_populates="interactions")

    __table_args__ = (
        Index("idx_interactions_cv_ts", "cv_id", "ts"),
        Index("idx_interactions_event_ts", "event_type", "ts"),
    )


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    insights_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    token_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("idx_insights_cv_created", "cv_id", "created_at"),)


class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cv_id: Mapped[str | None] = mapped_column(ForeignKey("cv_documents.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    search_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_configs.id", ondelete="SET NULL"), nullable=True
    )
    scheduler_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("scheduler_runs.id", ondelete="SET NULL"), nullable=True
    )
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    token_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    session: Mapped[CVSession | None] = relationship("CVSession", back_populates="llm_usage_logs")
    search: Mapped[SearchConfig | None] = relationship("SearchConfig", back_populates="llm_usage_logs")
    run: Mapped[SchedulerRun | None] = relationship("SchedulerRun", back_populates="llm_usage_logs")

    __table_args__ = (
        Index("idx_llm_usage_created", "created_at"),
        Index("idx_llm_usage_model_created", "model_name", "created_at"),
        Index("idx_llm_usage_feature_created", "feature", "created_at"),
    )
