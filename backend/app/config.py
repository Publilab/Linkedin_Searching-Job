from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CV LinkedIn Job Finder"
    app_env: str = "dev"

    database_url: str = Field(default="sqlite:///./app.db")
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])

    scheduler_interval_minutes: int = 30
    scheduler_poll_seconds: int = 15

    default_search_limit: int = 50

    llm_enabled: bool = True
    llm_provider: str = "google_gemini"
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: int = 25
    llm_max_retries: int = 3
    llm_max_jobs_per_run: int = 25
    llm_prompt_version: str = "v1"


settings = Settings()
