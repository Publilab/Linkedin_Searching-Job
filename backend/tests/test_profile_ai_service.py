from app.config import settings
from app.services.llm.pii import redact_pii
from app.services.profile_ai_service import analyze_profile


def test_redact_pii_masks_email_phone_and_url():
    text = "John Doe\njohn.doe@example.com\n+56 9 1234 5678\nhttps://linkedin.com/in/johndoe"
    redacted = redact_pii(text)

    assert "john.doe@example.com" not in redacted
    assert "+56 9 1234 5678" not in redacted
    assert "linkedin.com" not in redacted
    assert "[EMAIL]" in redacted
    assert "[PHONE]" in redacted
    assert "[URL]" in redacted


def test_analyze_profile_fallback_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    summary = {
        "highlights": ["Senior Backend Engineer"],
        "skills": ["Python", "FastAPI", "SQL"],
        "experience": ["Backend Engineer at Acme 2021-2024"],
        "education": ["Bachelor in Computer Science"],
        "languages": ["English", "Spanish"],
    }

    result = analyze_profile("John Doe email@example.com", summary)

    assert result["llm_status"] == "fallback"
    assert result["analysis"]["llm_status"] == "fallback"
    assert result["profile_fingerprint"]
    assert result["llm_strategy_json"]["recommended_queries"]


def test_analyze_profile_fallback_infers_academic_and_hr_roles(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    summary = {
        "highlights": ["Administrador Publico con experiencia academica y en RRHH"],
        "skills": ["Gestion de personas", "Capacitacion", "Politicas publicas"],
        "experience": [
            "Academico y relator de programas publicos 2021-2024",
            "Analista de recursos humanos 2018-2021",
        ],
        "education": ["Administrador Publico", "Diplomado en Gestion de Personas y RRHH"],
        "languages": ["Spanish"],
    }

    result = analyze_profile("sample cv text", summary)
    roles_text = " ".join(result["analysis"]["target_roles"] + result["analysis"]["secondary_roles"]).lower()
    queries_text = " ".join(result["llm_strategy_json"]["recommended_queries"]).lower()

    assert "academico" in roles_text or "docente" in roles_text
    assert "recursos humanos" in roles_text or "people operations" in roles_text
    assert "recursos humanos" in queries_text or "rrhh" in queries_text


def test_analyze_profile_merges_llm_output_with_local_role_inference(monkeypatch):
    class FakeGeminiClient:
        @property
        def enabled(self):
            return True

        def generate_json(self, _prompt: str):
            return {
                "highlights": ["Administrador Publico"],
                "skills": ["Gestion Publica", "Gestion de Personas"],
                "experience": [
                    "Academico y relator de programas publicos 2021-2024",
                    "Jefe del departamento de recursos humanos 2018-2021",
                ],
                "education": ["Administrador Publico"],
                "languages": ["Spanish"],
                # Intentionally incomplete to verify merge with deterministic inference.
                "target_roles": ["Administrador Publico"],
                "secondary_roles": [],
                "seniority": "mid",
                "industries": ["Public Sector"],
                "strengths": ["Gestion publica"],
                "skill_gaps": [],
                "recommended_queries": ["administrador publico"],
            }

    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr("app.services.profile_ai_service.GeminiLLMClient", FakeGeminiClient)

    summary = {
        "highlights": ["Administrador Publico"],
        "skills": ["Gestion de personas"],
        "experience": [
            "Academico y relator de programas publicos 2021-2024",
            "Jefe del departamento de recursos humanos 2018-2021",
        ],
        "education": ["Administrador Publico"],
        "languages": ["Spanish"],
    }

    result = analyze_profile("sample cv text", summary)
    assert result["llm_status"] == "ok"

    roles_text = " ".join(result["analysis"]["target_roles"] + result["analysis"]["secondary_roles"]).lower()
    queries_text = " ".join(result["analysis"]["recommended_queries"]).lower()

    assert "academico" in roles_text or "docente" in roles_text
    assert "recursos humanos" in roles_text or "people operations" in roles_text
    assert "recursos humanos" in queries_text or "rrhh" in queries_text
