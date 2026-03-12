from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import LLMSettingsOut, LLMSettingsTestOut, LLMSettingsUpdateIn
from app.services.runtime_settings import get_llm_settings_public, test_llm_settings, update_llm_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm", response_model=LLMSettingsOut)
def get_llm_settings(db: Session = Depends(get_db)) -> LLMSettingsOut:
    payload = get_llm_settings_public(db)
    return LLMSettingsOut(**payload)


@router.put("/llm", response_model=LLMSettingsOut)
def put_llm_settings(payload: LLMSettingsUpdateIn, db: Session = Depends(get_db)) -> LLMSettingsOut:
    try:
        out = update_llm_settings(
            db,
            provider=payload.provider,
            model=payload.model,
            llm_enabled=payload.llm_enabled,
            api_key=payload.api_key,
            openai_base_url=payload.openai_base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return LLMSettingsOut(**out)


@router.post("/llm/test", response_model=LLMSettingsTestOut)
def post_llm_test(db: Session = Depends(get_db)) -> LLMSettingsTestOut:
    current = get_llm_settings_public(db)
    result = test_llm_settings(db)
    return LLMSettingsTestOut(
        ok=bool(result.get("ok")),
        message=str(result.get("message") or "Unknown response"),
        provider=current["provider"],
        model=current["model"],
    )
