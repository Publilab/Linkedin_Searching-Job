from __future__ import annotations

from app.config import settings
from app.services.llm.client import GeminiLLMClient
from app.services.llm.openai_client import OpenAILLMClient


def get_llm_client():
    provider = (settings.llm_provider or "").strip().lower()
    if provider == "openai":
        return OpenAILLMClient()
    return GeminiLLMClient()

