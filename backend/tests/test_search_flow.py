from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.db import SessionLocal
from app.main import app
from app.services.search_service import run_search_once


def test_search_flow_with_mocked_scraper(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Senior Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": "123",
                "canonical_url": "https://www.linkedin.com/jobs/view/123",
                "canonical_url_hash": "h1",
                "title": "Data Analyst",
                "company": "Acme",
                "location": "Santiago",
                "description": "Python SQL analyst role",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 20,
                "applicant_count_raw": "20 applicants",
                "posted_at": None,
            }
        ]

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        upload = client.post("/api/cv/upload", files=files)
        assert upload.status_code == 200
        cv_id = upload.json()["cv_id"]

        save = client.put(
            f"/api/cv/{cv_id}/summary",
            json={
                "summary": {
                    "highlights": ["Data Analyst"],
                    "skills": ["python", "sql"],
                    "experience": ["Data Analyst"],
                    "education": ["Bachelor"],
                    "languages": ["English"],
                }
            },
        )
        assert save.status_code == 200

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
        body = created.json()

        assert body["results"]["total"] >= 1
        first = body["results"]["items"][0]
        assert first["applicant_count"] == 20
        assert "llm_fit_score" in first
        assert "final_score" in first
        assert "job_category" in first

        check = client.patch(
            f"/api/searches/results/{first['result_id']}/check",
            json={"checked": True},
        )
        assert check.status_code == 200

        fetched = client.get(f"/api/searches/{body['search_id']}/results?sort_by=best_fit")
        assert fetched.status_code == 200
        assert fetched.json()["items"][0]["checked"] is True

        facets = client.get(f"/api/searches/{body['search_id']}/facets")
        assert facets.status_code == 200
        assert "categories" in facets.json()


def test_dedupe_prioritizes_external_job_id(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Engineer\nSkills: Python, SQL\nEducation: Bachelor",
    )

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": "999",
                "canonical_url": "https://www.linkedin.com/jobs/view/999?trk=foo",
                "canonical_url_hash": "h-old",
                "title": "Data Engineer",
                "company": "Example",
                "location": "Santiago",
                "description": "SQL",
                "modality": "remote",
                "easy_apply": False,
                "applicant_count": 0,
                "applicant_count_raw": None,
                "posted_at": None,
            },
            {
                "source": "linkedin_public",
                "external_job_id": "999",
                "canonical_url": "https://www.linkedin.com/jobs/view/999",
                "canonical_url_hash": "h-new",
                "title": "Data Engineer",
                "company": "Example",
                "location": "Santiago",
                "description": "SQL Python pipelines and cloud",
                "modality": "remote",
                "easy_apply": True,
                "applicant_count": 37,
                "applicant_count_raw": "37 applicants",
                "posted_at": None,
            },
        ]

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]

        client.put(
            f"/api/cv/{cv_id}/summary",
            json={
                "summary": {
                    "highlights": ["Data Engineer"],
                    "skills": ["python", "sql"],
                    "experience": ["Data Engineer"],
                    "education": ["Bachelor"],
                    "languages": ["English"],
                }
            },
        )

        created = client.post(
            "/api/searches",
            json={
                "cv_id": cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 24,
                "keywords": ["Data Engineer"],
            },
        )
        assert created.status_code == 200

    with SessionLocal() as db:
        postings = db.scalars(
            select(models.JobPosting).where(models.JobPosting.external_job_id == "999")
        ).all()
        assert len(postings) == 1
        assert postings[0].applicant_count == 37

        runs = db.scalars(select(models.SchedulerRun)).all()
        assert len(runs) >= 1


def test_search_config_can_be_updated(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: RRHH, Policy\nEducation: Administrador Publico",
    )
    monkeypatch.setattr("app.services.search_service.scrape_jobs", lambda **kwargs: [])

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]

        created = client.post(
            "/api/searches",
            json={
                "cv_id": cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 24,
                "keywords": ["administrador publico"],
            },
        )
        assert created.status_code == 200
        search_id = created.json()["search_id"]

        updated = client.patch(
            f"/api/searches/{search_id}",
            json={
                "country": "Chile",
                "city": "Valparaiso",
                "time_window_hours": 3,
                "keywords": ["academico", "analista de recursos humanos"],
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["city"] == "Valparaiso"
        assert body["time_window_hours"] == 3
        assert body["keywords"] == ["academico", "analista de recursos humanos"]

        fetched = client.get(f"/api/searches/{search_id}")
        assert fetched.status_code == 200
        fetched_body = fetched.json()
        assert fetched_body["city"] == "Valparaiso"
        assert fetched_body["time_window_hours"] == 3


def test_search_accepts_week_and_month_windows(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: RRHH, Policy\nEducation: Administrador Publico",
    )
    monkeypatch.setattr("app.services.search_service.scrape_jobs", lambda **kwargs: [])

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]

        created = client.post(
            "/api/searches",
            json={
                "cv_id": cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 168,
                "keywords": ["administrador publico"],
            },
        )
        assert created.status_code == 200
        search_id = created.json()["search_id"]

        updated = client.patch(
            f"/api/searches/{search_id}",
            json={
                "time_window_hours": 720,
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["time_window_hours"] == 720


def test_results_endpoint_pagination(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": f"p-{idx}",
                "canonical_url": f"https://www.linkedin.com/jobs/view/p-{idx}",
                "canonical_url_hash": f"hp-{idx}",
                "title": f"Data Analyst {idx}",
                "company": "Acme",
                "location": "Santiago",
                "description": f"Python SQL analyst role {idx}",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 10 + idx,
                "applicant_count_raw": f"{10 + idx} applicants",
                "posted_at": None,
            }
            for idx in range(1, 6)
        ]

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]

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

        page1 = client.get(f"/api/searches/{search_id}/results?page=1&page_size=2")
        assert page1.status_code == 200
        body1 = page1.json()
        assert body1["total"] == 5
        assert body1["page"] == 1
        assert body1["page_size"] == 2
        assert body1["total_pages"] == 3
        assert body1["has_prev"] is False
        assert body1["has_next"] is True
        assert len(body1["items"]) == 2

        page3 = client.get(f"/api/searches/{search_id}/results?page=3&page_size=2")
        assert page3.status_code == 200
        body3 = page3.json()
        assert body3["total"] == 5
        assert body3["page"] == 3
        assert body3["page_size"] == 2
        assert body3["total_pages"] == 3
        assert body3["has_prev"] is True
        assert body3["has_next"] is False
        assert len(body3["items"]) == 1


def test_scheduled_run_forces_one_hour_window(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: Policy, RRHH\nEducation: Administrador Publico",
    )

    seen_windows: list[int] = []

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        seen_windows.append(int(time_window_hours))
        return []

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]

        created = client.post(
            "/api/searches",
            json={
                "cv_id": cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 72,
                "keywords": ["administrador publico"],
            },
        )
        assert created.status_code == 200
        search_id = created.json()["search_id"]

    seen_windows.clear()
    run_search_once(SessionLocal, search_id, run_type="scheduled")

    assert seen_windows
    assert set(seen_windows) == {1}


def test_excludes_jobs_with_100_or_more_applicants(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": "101",
                "canonical_url": "https://www.linkedin.com/jobs/view/101",
                "canonical_url_hash": "h101",
                "title": "Senior Data Analyst",
                "company": "Acme",
                "location": "Santiago",
                "description": "Python SQL analytics",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 100,
                "applicant_count_raw": "100 applicants",
                "posted_at": None,
            },
            {
                "source": "linkedin_public",
                "external_job_id": "102",
                "canonical_url": "https://www.linkedin.com/jobs/view/102",
                "canonical_url_hash": "h102",
                "title": "Data Analyst",
                "company": "Acme",
                "location": "Santiago",
                "description": "Python SQL analyst role",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 99,
                "applicant_count_raw": "99 applicants",
                "posted_at": None,
            },
        ]

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]
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
        items = created.json()["results"]["items"]
        assert len(items) == 1
        assert items[0]["applicant_count"] == 99


def test_llm_fit_fallback_uses_match_percent_when_zero(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    def fake_scrape_jobs(keywords, location, time_window_hours, **kwargs):
        return [
            {
                "source": "linkedin_public",
                "external_job_id": "201",
                "canonical_url": "https://www.linkedin.com/jobs/view/201",
                "canonical_url_hash": "h201",
                "title": "Data Analyst",
                "company": "Acme",
                "location": "Santiago",
                "description": "Python SQL analyst role",
                "modality": "hybrid",
                "easy_apply": True,
                "applicant_count": 20,
                "applicant_count_raw": "20 applicants",
                "posted_at": None,
            }
        ]

    def fake_evaluate_job_fit(*args, **kwargs):
        return {
            "job_category": "General",
            "job_subcategory": "Other",
            "llm_fit_score": 0.0,
            "fit_reasons": [],
            "gap_notes": [],
            "role_alignment": [],
            "llm_status": "fallback",
            "llm_analysis_hash": "hash",
            "llm_model": None,
            "llm_prompt_version": "v1",
            "llm_error": "forced fallback",
        }

    monkeypatch.setattr("app.services.search_service.scrape_jobs", fake_scrape_jobs)
    monkeypatch.setattr("app.services.search_service.evaluate_job_fit", fake_evaluate_job_fit)

    with TestClient(app) as client:
        files = {"file": ("cv.pdf", BytesIO(b"dummy"), "application/pdf")}
        cv_id = client.post("/api/cv/upload", files=files).json()["cv_id"]
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
        item = created.json()["results"]["items"][0]
        assert item["match_percent"] > 0
        assert item["llm_fit_score"] == item["match_percent"]
