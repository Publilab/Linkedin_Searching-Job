from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, APIStatusError, OpenAI

from app.config import settings
from app.services.llm.client import LLMClientError
from app.services.llm.prompts import build_repair_prompt

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class OpenAILLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ):
        configured_key = settings.openai_api_key
        self.api_key = api_key if api_key is not None else configured_key
        self.base_url = base_url if base_url is not None else settings.openai_base_url
        self.model = model if model is not None else settings.llm_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.llm_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.llm_max_retries

    @property
    def enabled(self) -> bool:
        return bool(
            settings.llm_enabled
            and settings.llm_provider == "openai"
            and self.api_key
            and self.model
        )

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self.enabled:
            raise LLMClientError("LLM disabled or missing OpenAI configuration")

        raw_text = self._call_with_retry(prompt)
        parsed = _parse_json_payload(raw_text)
        if parsed is not None:
            return parsed

        repair_text = self._call_with_retry(build_repair_prompt(raw_text))
        repaired = _parse_json_payload(repair_text)
        if repaired is not None:
            return repaired

        raise LLMClientError("OpenAI returned non-JSON content")

    def _call_with_retry(self, prompt: str) -> str:
        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.responses.create(
                    model=self.model,
                    input=prompt,
                )
                text = _extract_text(response)
                if text is None:
                    last_error = "Empty OpenAI response text"
                    if attempt < self.max_retries:
                        time.sleep(_backoff_seconds(attempt))
                        continue
                    raise LLMClientError(last_error)
                return text
            except APIStatusError as exc:
                status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
                body = str(exc)
                last_error = f"HTTP {status_code}: {body[:300]}" if status_code else body[:300]
                if status_code in RETRY_STATUS_CODES and attempt < self.max_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise LLMClientError(last_error) from exc
            except (APITimeoutError, APIConnectionError) as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise LLMClientError(last_error) from exc
            except APIError as exc:
                last_error = str(exc)
                raise LLMClientError(last_error) from exc
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue
                raise LLMClientError(last_error) from exc

        raise LLMClientError(last_error)


def _extract_text(response: Any) -> str | None:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    payload = response.model_dump() if hasattr(response, "model_dump") else None
    if not isinstance(payload, dict):
        return None

    # Expected shape from Responses API.
    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())

    if chunks:
        return "\n".join(chunks)
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
