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


class LLMRoleProbability(BaseModel):
    role: str = ""
    probability: float = 0.0
    why: list[str] = Field(default_factory=list)


class LLMGapItem(BaseModel):
    gap: str = ""
    impact: str = "medium"
    fix: list[str] = Field(default_factory=list)


class LLMFitOutlook(BaseModel):
    target_roles: list[LLMRoleProbability] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[LLMGapItem] = Field(default_factory=list)


class LLMRerankRule(BaseModel):
    rule: str = ""
    weight: float = 0.0


class LLMSearchImprovements(BaseModel):
    add_queries: list[str] = Field(default_factory=list)
    remove_queries: list[str] = Field(default_factory=list)
    recommended_filters: dict = Field(default_factory=dict)
    rerank_rules: list[LLMRerankRule] = Field(default_factory=list)


class LLMCVRecommendation(BaseModel):
    change: str = ""
    reason: str = ""
    example_text: str | None = None


class LLMWeeklyPlanItem(BaseModel):
    day: str = ""
    actions: list[str] = Field(default_factory=list)


class LLMFeedbackInsights(BaseModel):
    fit_outlook: LLMFitOutlook = Field(default_factory=LLMFitOutlook)
    search_improvements: LLMSearchImprovements = Field(default_factory=LLMSearchImprovements)
    cv_recommendations: list[LLMCVRecommendation] = Field(default_factory=list)
    weekly_plan: list[LLMWeeklyPlanItem] = Field(default_factory=list)
