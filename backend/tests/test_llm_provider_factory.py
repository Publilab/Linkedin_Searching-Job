from app.config import settings
from app.services.llm.client import GeminiLLMClient
from app.services.llm.factory import get_llm_client
from app.services.llm.openai_client import OpenAILLMClient


def test_factory_returns_openai_client_for_openai_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "fake-openai-key")
    monkeypatch.setattr(settings, "llm_model", "gpt-5-mini")

    client = get_llm_client()
    assert isinstance(client, OpenAILLMClient)
    assert client.enabled is True


def test_factory_returns_gemini_client_for_gemini_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "google_gemini")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", "fake-gemini-key")
    monkeypatch.setattr(settings, "llm_model", "gemini-2.0-flash")

    client = get_llm_client()
    assert isinstance(client, GeminiLLMClient)
    assert client.enabled is True


def test_openai_client_is_disabled_without_openai_key_even_if_gemini_key_exists(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key-should-not-be-used")
    monkeypatch.setattr(settings, "llm_model", "gpt-5-mini")

    client = OpenAILLMClient()
    assert client.enabled is False
