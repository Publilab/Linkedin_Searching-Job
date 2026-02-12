from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from app.config import settings
from app.services.llm.prompts import build_repair_prompt


class LLMClientError(RuntimeError):
    pass


class GeminiLLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        provider: str | None = None,
        llm_enabled: bool | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model if model is not None else settings.llm_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.llm_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.llm_max_retries
        self.provider = provider if provider is not None else settings.llm_provider
        self.runtime_enabled = llm_enabled if llm_enabled is not None else settings.llm_enabled

    @property
    def enabled(self) -> bool:
        return bool(
            self.runtime_enabled
            and str(self.provider or "").strip().lower() == "google_gemini"
            and self.api_key
            and self.model
        )

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self.enabled:
            raise LLMClientError("LLM disabled or missing Gemini configuration")

        raw_text = self._call_with_retry(prompt)
        parsed = _parse_json_payload(raw_text)
        if parsed is not None:
            return parsed

        repair_text = self._call_with_retry(build_repair_prompt(raw_text))
        repaired = _parse_json_payload(repair_text)
        if repaired is not None:
            return repaired

        raise LLMClientError("Gemini returned non-JSON content")

    def _call_with_retry(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(url, json=payload)
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                        time.sleep(_backoff_seconds(attempt))
                        continue
                    raise LLMClientError(last_error)

                data = response.json()
                text = _extract_text(data)
                if text is None:
                    last_error = "Empty Gemini candidate text"
                    if attempt < self.max_retries:
                        time.sleep(_backoff_seconds(attempt))
                        continue
                    raise LLMClientError(last_error)
                return text
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise LLMClientError(last_error) from exc

        raise LLMClientError(last_error)


def _extract_text(payload: dict[str, Any]) -> str | None:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None

    content = candidates[0].get("content")
    if not isinstance(content, dict):
        return None

    parts = content.get("parts")
    if not isinstance(parts, list):
        return None

    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return part["text"]
    return None


def _parse_json_payload(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None

    text = raw_text.strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    return loaded if isinstance(loaded, dict) else None


def _backoff_seconds(attempt: int) -> float:
    base = 0.6
    cap = 6.0
    return min(cap, base * (2 ** (attempt - 1)))
