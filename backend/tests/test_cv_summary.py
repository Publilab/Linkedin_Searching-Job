from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app
from app.services.cv_summary import summarize_cv_text


def test_cv_summary_extracts_core_sections():
    text = """
    John Doe
    Senior Data Analyst
    Experience
    Data Analyst at Acme 2020-2024
    Skills: Python, SQL, Power BI, Docker
    Education: Bachelor in Computer Science
    Languages: English, Spanish
    """
    out = summarize_cv_text(text)

    assert "python" in out["skills"]
    assert any("Analyst" in line for line in out["experience"])
    assert out["education"]
    assert "English" in out["languages"]


def test_cv_summary_uses_full_document_not_only_first_paragraph():
    text = """
    Perfil profesional
    Profesional con experiencia en gestion publica.

    Formacion academica
    Administrador Publico - Universidad de Santiago
    Diplomado en Compras Publicas

    Experiencia laboral
    Coordinador de programas municipales 2019 - 2023
    Analista de politicas publicas 2016 - 2019
    """

    out = summarize_cv_text(text)

    joined_edu = " ".join(out["education"]).lower()
    joined_exp = " ".join(out["experience"]).lower()

    assert "administrador publico" in joined_edu or "administrador público" in joined_edu
    assert "coordinador" in joined_exp
    assert "analista" in joined_exp


def test_cv_summary_includes_academic_and_hr_experience():
    text = """
    Perfil profesional
    Administrador Publico con experiencia en docencia y gestion de personas.

    Experiencia laboral
    Academico y relator en gestion publica 2021 - 2024
    Analista de recursos humanos en servicio publico 2018 - 2021

    Formacion academica
    Administrador Publico
    Diplomado en Gestion de Personas y RRHH
    """

    out = summarize_cv_text(text)
    joined_exp = " ".join(out["experience"]).lower()
    joined_edu = " ".join(out["education"]).lower()

    assert "academico" in joined_exp
    assert "recursos humanos" in joined_exp or "rrhh" in joined_exp
    assert "administrador publico" in joined_edu


def test_cv_analyze_endpoint(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Senior Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    with TestClient(app) as client:
        upload = client.post(
            "/api/cv/upload",
            files={"file": ("cv.pdf", BytesIO(b"x"), "application/pdf")},
        )
        assert upload.status_code == 200
        cv_id = upload.json()["cv_id"]

        analyze = client.post(f"/api/cv/{cv_id}/analyze")
        assert analyze.status_code == 200
        body = analyze.json()
        assert "analysis" in body
        assert "recommended_queries" in body["analysis"]

        strategy = client.get(f"/api/cv/{cv_id}/strategy")
        assert strategy.status_code == 200
        strategy_body = strategy.json()
        assert "recommended_queries" in strategy_body
        assert "market_roles" in strategy_body
