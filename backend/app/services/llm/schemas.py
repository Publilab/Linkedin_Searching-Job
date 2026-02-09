from __future__ import annotations

from pydantic import BaseModel, Field


class LLMCVExtraction(BaseModel):
    highlights: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    target_roles: list[str] = Field(default_factory=list)
    secondary_roles: list[str] = Field(default_factory=list)
    seniority: str = "unknown"
    industries: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    recommended_queries: list[str] = Field(default_factory=list)


class LLMJobEvaluation(BaseModel):
    job_category: str | None = None
    job_subcategory: str | None = None
    llm_fit_score: float = 0.0
    fit_reasons: list[str] = Field(default_factory=list)
    gap_notes: list[str] = Field(default_factory=list)
    role_alignment: list[str] = Field(default_factory=list)
