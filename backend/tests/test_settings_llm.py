from fastapi.testclient import TestClient

from app.main import app


def test_get_llm_settings(monkeypatch):
    monkeypatch.setattr(
        "app.routers.settings.get_llm_settings_public",
        lambda _db: {
            "provider": "openai",
            "model": "gpt-5-mini",
            "llm_enabled": True,
            "key_present": True,
            "openai_base_url": None,
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5-mini"
    assert body["llm_enabled"] is True
    assert body["key_present"] is True


def test_put_llm_settings(monkeypatch):
    monkeypatch.setattr(
        "app.routers.settings.update_llm_settings",
        lambda _db, **_kwargs: {
            "provider": "google_gemini",
            "model": "gemini-2.0-flash",
            "llm_enabled": True,
            "key_present": True,
            "openai_base_url": None,
        },
    )

    payload = {
        "provider": "google_gemini",
        "model": "gemini-2.0-flash",
        "llm_enabled": True,
        "api_key": "AIza...",
    }

    with TestClient(app) as client:
        response = client.put("/api/settings/llm", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "google_gemini"
    assert body["model"] == "gemini-2.0-flash"
    assert body["key_present"] is True


def test_post_llm_test(monkeypatch):
    monkeypatch.setattr(
        "app.routers.settings.get_llm_settings_public",
        lambda _db: {
            "provider": "openai",
            "model": "gpt-5-mini",
            "llm_enabled": True,
            "key_present": True,
            "openai_base_url": None,
        },
    )
    monkeypatch.setattr(
        "app.routers.settings.test_llm_settings",
        lambda _db: {"ok": True, "message": "ok"},
    )

    with TestClient(app) as client:
        response = client.post("/api/settings/llm/test")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5-mini"
