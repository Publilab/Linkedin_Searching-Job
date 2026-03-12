from __future__ import annotations

from app.services.llm.client import GeminiLLMClient
from app.services.llm.openai_client import OpenAILLMClient
from app.services.runtime_settings import load_runtime_llm_config


def get_llm_client():
    cfg = load_runtime_llm_config()
    provider = (cfg.provider or "").strip().lower()

    if provider == "openai":
        return OpenAILLMClient(
            api_key=cfg.api_key,
            base_url=cfg.openai_base_url,
            model=cfg.model,
            timeout_seconds=cfg.timeout_seconds,
            max_retries=cfg.max_retries,
            provider=cfg.provider,
            llm_enabled=cfg.llm_enabled,
        )

    return GeminiLLMClient(
        api_key=cfg.api_key,
        model=cfg.model,
        timeout_seconds=cfg.timeout_seconds,
        max_retries=cfg.max_retries,
        provider=cfg.provider,
        llm_enabled=cfg.llm_enabled,
    )
