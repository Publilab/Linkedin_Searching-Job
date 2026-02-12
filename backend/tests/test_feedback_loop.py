from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.db import SessionLocal
from app.main import app


def test_interaction_learning_improves_next_scoring(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )
    monkeypatch.setattr("app.services.market_demand_service._fetch_internet_demand", lambda terms: [])

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": "feedback-1",
                "canonical_url": "https://www.linkedin.com/jobs/view/feedback-1",
                "canonical_url_hash": "h-feedback-1",
                "title": "Data Analyst",
                "company": "Acme",
                "location": "Santiago",
                "description": "Python SQL analytics role",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 12,
                "applicant_count_raw": "12 applicants",
                "posted_at": None,
            }
        ]

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        upload = client.post(
            "/api/cv/upload",
            files={"file": ("cv-feedback.pdf", BytesIO(b"feedback-a"), "application/pdf")},
        )
        assert upload.status_code == 200
        cv_id = upload.json()["cv_id"]
        session_id = upload.json()["session_id"]

        created = client.post(
            "/api/searches",
            json={
                "cv_id": cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 24,
                "keywords": ["Data Analyst"],
            },
        )
        assert created.status_code == 200
        search_id = created.json()["search_id"]
        first_row = created.json()["results"]["items"][0]
        first_score = float(first_row["final_score"])

        logged = client.post(
            "/api/interactions",
            json={
                "cv_id": cv_id,
                "session_id": session_id,
                "search_id": search_id,
                "result_id": first_row["result_id"],
                "job_id": first_row["job_id"],
                "event_type": "open",
                "dwell_ms": 95000,
            },
        )
        assert logged.status_code == 200

        rerun = client.post(f"/api/searches/{search_id}/run")
        assert rerun.status_code == 200

        fetched = client.get(f"/api/searches/{search_id}/results?sort_by=best_fit")
        assert fetched.status_code == 200
        rows = fetched.json()["items"]
        assert rows
        second_score = float(rows[0]["final_score"])
        assert second_score >= first_score

    with SessionLocal() as db:
        profile = db.scalar(select(models.CandidateProfile).where(models.CandidateProfile.cv_id == cv_id))
        assert profile is not None
        prefs = profile.learned_preferences_json or {}
        title_scores = prefs.get("title_scores") or {}
        assert "data analyst" in title_scores
        assert float(title_scores["data analyst"]) > 0


def test_generate_insight_and_fetch_latest(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: Gestion Publica, RRHH\nEducation: Administrador Publico",
    )
    monkeypatch.setattr("app.services.market_demand_service._fetch_internet_demand", lambda terms: [])
    monkeypatch.setattr("app.services.search_service.scrape_jobs", lambda **kwargs: [])

    with TestClient(app) as client:
        upload = client.post(
            "/api/cv/upload",
            files={"file": ("cv-insight.pdf", BytesIO(b"feedback-b"), "application/pdf")},
        )
        assert upload.status_code == 200
        cv_id = upload.json()["cv_id"]

        generated = client.post(
            f"/api/insights/cv/{cv_id}/generate",
            json={"days": 7},
        )
        assert generated.status_code == 200
        insight = generated.json()
        assert insight["cv_id"] == cv_id
        assert "insights" in insight
        assert "fit_outlook" in insight["insights"]
        assert "search_improvements" in insight["insights"]

        latest = client.get(f"/api/insights/cv/{cv_id}/latest")
        assert latest.status_code == 200
        latest_body = latest.json()
        assert latest_body is not None
        assert latest_body["insight_id"] == insight["insight_id"]
