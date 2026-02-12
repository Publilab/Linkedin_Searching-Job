from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal

_SECRET_SERVICE_NAME = "seekjob.llm"
_OPENAI_KEY = "openai_api_key"
_GEMINI_KEY = "gemini_api_key"
_RUNTIME_SETTING_KEYS = {
    "llm_provider",
    "llm_model",
    "llm_enabled",
    "openai_base_url",
    "llm_prompt_version",
    "llm_timeout_seconds",
    "llm_max_retries",
    "llm_max_jobs_per_run",
}


@dataclass
class LLMRuntimeConfig:
    llm_enabled: bool
    provider: str
    model: str
    prompt_version: str
    timeout_seconds: int
    max_retries: int
    max_jobs_per_run: int
    openai_base_url: str | None
    api_key: str | None


def get_app_data_dir() -> Path:
    raw = (settings.seekjob_data_dir or "").strip()
    if raw:
        path = Path(raw).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    fallback = Path.cwd()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def load_runtime_llm_config(db: Session | None = None) -> LLMRuntimeConfig:
    if db is None:
        with SessionLocal() as own_db:
            return load_runtime_llm_config(own_db)

    cfg_map = _load_settings_map(db)
    secrets = _load_llm_secrets()

    provider = str(cfg_map.get("llm_provider") or settings.llm_provider or "openai").strip().lower()
    if provider not in {"openai", "google_gemini"}:
        provider = "openai"

    model = str(cfg_map.get("llm_model") or settings.llm_model or "gpt-5-mini").strip()
    if not model:
        model = "gpt-5-mini"

    prompt_version = str(cfg_map.get("llm_prompt_version") or settings.llm_prompt_version or "v1").strip() or "v1"
    timeout_seconds = _coerce_int(cfg_map.get("llm_timeout_seconds"), settings.llm_timeout_seconds)
    max_retries = _coerce_int(cfg_map.get("llm_max_retries"), settings.llm_max_retries)
    max_jobs_per_run = _coerce_int(cfg_map.get("llm_max_jobs_per_run"), settings.llm_max_jobs_per_run)

    openai_base_url = cfg_map.get("openai_base_url")
    if openai_base_url is None:
        openai_base_url = settings.openai_base_url
    if isinstance(openai_base_url, str):
        openai_base_url = openai_base_url.strip() or None
    else:
        openai_base_url = None

    llm_enabled = _coerce_bool(cfg_map.get("llm_enabled"), settings.llm_enabled)

    api_key = None
    if provider == "openai":
        api_key = secrets.get(_OPENAI_KEY) or settings.openai_api_key
    elif provider == "google_gemini":
        api_key = secrets.get(_GEMINI_KEY) or settings.gemini_api_key

    return LLMRuntimeConfig(
        llm_enabled=llm_enabled,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_jobs_per_run=max_jobs_per_run,
        openai_base_url=openai_base_url,
        api_key=api_key,
    )


def get_llm_settings_public(db: Session | None = None) -> dict[str, Any]:
    if db is None:
        with SessionLocal() as own_db:
            return get_llm_settings_public(own_db)

    cfg = load_runtime_llm_config(db)
    secrets = _load_llm_secrets()

    key_present = False
    if cfg.provider == "openai":
        key_present = bool((secrets.get(_OPENAI_KEY) or settings.openai_api_key or "").strip())
    elif cfg.provider == "google_gemini":
        key_present = bool((secrets.get(_GEMINI_KEY) or settings.gemini_api_key or "").strip())

    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "llm_enabled": cfg.llm_enabled,
        "key_present": key_present,
        "openai_base_url": cfg.openai_base_url,
    }


def update_llm_settings(
    db: Session,
    *,
    provider: str,
    model: str,
    llm_enabled: bool,
    api_key: str | None,
    openai_base_url: str | None,
) -> dict[str, Any]:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in {"openai", "google_gemini"}:
        raise ValueError("provider must be 'openai' or 'google_gemini'")

    normalized_model = (model or "").strip()
    if not normalized_model:
        raise ValueError("model is required")

    payload = {
        "llm_provider": normalized_provider,
        "llm_model": normalized_model,
        "llm_enabled": bool(llm_enabled),
        "openai_base_url": (openai_base_url or "").strip() or None,
    }
    _upsert_settings(db, payload)

    if api_key is not None:
        cleaned_key = api_key.strip()
        _store_llm_secret(
            _OPENAI_KEY if normalized_provider == "openai" else _GEMINI_KEY,
            cleaned_key,
        )

    db.commit()
    return get_llm_settings_public(db)


def test_llm_settings(db: Session) -> dict[str, Any]:
    from app.services.llm import LLMClientError, get_llm_client

    client = get_llm_client()
    if not client.enabled:
        return {
            "ok": False,
            "message": "LLM disabled or credentials missing for selected provider",
        }

    prompt = json.dumps(
        {
            "task": "healthcheck",
            "requirements": [
                "Return strict JSON only",
                "Set ok=true",
            ],
            "json_schema": {"ok": "boolean"},
        },
        ensure_ascii=True,
    )

    try:
        out = client.generate_json(prompt)
    except (LLMClientError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}

    return {
        "ok": bool(out.get("ok", False)),
        "message": "LLM configuration is valid" if bool(out.get("ok", False)) else "Unexpected LLM response",
    }


def _load_settings_map(db: Session) -> dict[str, Any]:
    out: dict[str, Any] = {}

    rows = db.execute(text("SELECT key, value_json FROM app_settings")).all()
    for row in rows:
        key = str(row[0] or "").strip()
        if not key or key not in _RUNTIME_SETTING_KEYS:
            continue

        raw_value = row[1]
        payload: Any = None

        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            try:
                payload = json.loads(raw_value)
            except json.JSONDecodeError:
                # Ignore malformed legacy rows instead of crashing runtime loading.
                continue
        else:
            payload = raw_value

        if isinstance(payload, dict) and "value" in payload:
            out[key] = payload.get("value")
        else:
            out[key] = payload

    return out


def _upsert_settings(db: Session, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in _RUNTIME_SETTING_KEYS:
            continue

        payload_json = json.dumps({"value": value}, ensure_ascii=True)

        updated = db.execute(
            text(
                """
                UPDATE app_settings
                SET value_json = :value_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = :key
                """
            ),
            {"key": key, "value_json": payload_json},
        )
        if updated.rowcount and updated.rowcount > 0:
            continue

        db.execute(
            text(
                """
                INSERT INTO app_settings (key, value_json, updated_at)
                VALUES (:key, :value_json, CURRENT_TIMESTAMP)
                """
            ),
            {"key": key, "value_json": payload_json},
        )


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(fallback)


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return int(fallback)


def _load_llm_secrets() -> dict[str, str]:
    secrets: dict[str, str] = {}

    keyring_loaded = False
    try:
        import keyring  # type: ignore

        for key_name in (_OPENAI_KEY, _GEMINI_KEY):
            value = keyring.get_password(_SECRET_SERVICE_NAME, key_name)
            if isinstance(value, str) and value.strip():
                secrets[key_name] = value.strip()
        keyring_loaded = True
    except Exception:
        keyring_loaded = False

    if keyring_loaded:
        return secrets

    fallback_path = _fallback_secret_file()
    if not fallback_path.exists():
        return secrets

    try:
        payload = json.loads(fallback_path.read_text())
    except Exception:
        return secrets

    if not isinstance(payload, dict):
        return secrets

    for key_name in (_OPENAI_KEY, _GEMINI_KEY):
        value = payload.get(key_name)
        if isinstance(value, str) and value.strip():
            secrets[key_name] = value.strip()

    return secrets


def _store_llm_secret(key_name: str, value: str) -> None:
    cleaned = value.strip()

    try:
        import keyring  # type: ignore

        keyring.set_password(_SECRET_SERVICE_NAME, key_name, cleaned)
        return
    except Exception:
        pass

    fallback_path = _fallback_secret_file()
    payload: dict[str, Any] = {}
    if fallback_path.exists():
        try:
            loaded = json.loads(fallback_path.read_text())
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}

    payload[key_name] = cleaned
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2))
    try:
        os.chmod(fallback_path, 0o600)
    except OSError:
        pass


def _fallback_secret_file() -> Path:
    configured = (settings.seekjob_secret_fallback_file or "").strip()
    if configured:
        return Path(configured).expanduser()
    return get_app_data_dir() / "llm_secrets.json"
