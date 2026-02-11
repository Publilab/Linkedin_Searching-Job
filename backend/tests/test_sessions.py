from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app


def test_upload_creates_session_and_supports_state_roundtrip(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Data Analyst\nSkills: Python, SQL\nEducation: Bachelor",
    )

    with TestClient(app) as client:
        upload = client.post(
            "/api/cv/upload",
            files={"file": ("cv.pdf", BytesIO(b"session-1"), "application/pdf")},
        )
        assert upload.status_code == 200
        body = upload.json()
        session_id = body.get("session_id")
        cv_id = body.get("cv_id")
        assert session_id
        assert cv_id

        current = client.get(f"/api/session/current?session_id={session_id}")
        assert current.status_code == 200
        current_body = current.json()["session"]
        assert current_body["session_id"] == session_id
        assert current_body["cv_id"] == cv_id
        assert current_body["cv_filename"] == "cv.pdf"
        assert current_body["candidate_name"] == "Data Analyst"
        assert current_body["analysis_executed_at"] is not None

        state = client.post(
            "/api/session/state",
            json={
                "session_id": session_id,
                "ui_state": {
                    "country": "Chile",
                    "city": "Santiago",
                    "time_window_hours": 24,
                    "query_items": [{"text": "Data Analyst", "enabled": True}],
                },
            },
        )
        assert state.status_code == 200
        state_body = state.json()
        assert state_body["ui_state"]["country"] == "Chile"
        assert state_body["ui_state"]["city"] == "Santiago"

        close = client.post("/api/session/close", json={"session_id": session_id})
        assert close.status_code == 200
        assert close.json()["status"] == "closed"

        closed_current = client.get(f"/api/session/current?session_id={session_id}")
        assert closed_current.status_code == 200
        closed_session = closed_current.json()["session"]
        if closed_session:
            assert closed_session["session_id"] != session_id

        history = client.get("/api/session/history?limit=20")
        assert history.status_code == 200
        items = history.json()["items"]
        assert isinstance(items, list)
        assert any(item["session_id"] == session_id for item in items)


def test_resume_session_and_link_active_search(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: RRHH, Policy\nEducation: Administrador Publico",
    )
    monkeypatch.setattr("app.services.search_service.scrape_jobs", lambda **kwargs: [])

    with TestClient(app) as client:
        first = client.post(
            "/api/cv/upload",
            files={"file": ("cv1.pdf", BytesIO(b"session-2"), "application/pdf")},
        )
        second = client.post(
            "/api/cv/upload",
            files={"file": ("cv2.pdf", BytesIO(b"session-3"), "application/pdf")},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        first_session_id = first.json()["session_id"]
        first_cv_id = first.json()["cv_id"]
        second_session_id = second.json()["session_id"]
        assert first_session_id and second_session_id

        current = client.get("/api/session/current")
        assert current.status_code == 200
        assert current.json()["session"]["session_id"] == second_session_id

        resumed = client.post("/api/session/resume", json={"session_id": first_session_id})
        assert resumed.status_code == 200
        assert resumed.json()["session_id"] == first_session_id
        assert resumed.json()["status"] == "active"

        created = client.post(
            "/api/searches",
            json={
                "cv_id": first_cv_id,
                "country": "Chile",
                "city": "Santiago",
                "time_window_hours": 24,
                "keywords": ["administrador publico"],
            },
        )
        assert created.status_code == 200
        search_id = created.json()["search_id"]

        refreshed = client.get(f"/api/session/current?session_id={first_session_id}")
        assert refreshed.status_code == 200
        refreshed_session = refreshed.json()["session"]
        assert refreshed_session["active_search_id"] == search_id


def test_upload_deduplicates_by_file_hash_and_keeps_session_history(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Public Administrator\nSkills: Policy, RRHH\nEducation: Administrador Publico",
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/cv/upload",
            files={"file": ("cv-original.pdf", BytesIO(b"same-content"), "application/pdf")},
        )
        second = client.post(
            "/api/cv/upload",
            files={"file": ("cv-duplicado.pdf", BytesIO(b"same-content"), "application/pdf")},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        first_body = first.json()
        second_body = second.json()
        assert first_body["cv_id"] == second_body["cv_id"]
        assert first_body["session_id"] == second_body["session_id"]

        history = client.get("/api/session/history?limit=10")
        assert history.status_code == 200
        items = history.json()["items"]
        matches = [item for item in items if item["cv_id"] == first_body["cv_id"]]
        assert len(matches) == 1


def test_delete_session_removes_row_from_history(monkeypatch):
    monkeypatch.setattr(
        "app.services.cv_extract._extract_pdf",
        lambda _: "Jane Doe\nSkills: Python\nEducation: Bachelor",
    )

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/cv/upload",
            files={"file": ("cv-delete.pdf", BytesIO(b"delete-session"), "application/pdf")},
        )
        assert uploaded.status_code == 200
        session_id = uploaded.json()["session_id"]
        assert session_id

        deleted = client.delete(f"/api/session/{session_id}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        history = client.get("/api/session/history?limit=50")
        assert history.status_code == 200
        session_ids = [item["session_id"] for item in history.json()["items"]]
        assert session_id not in session_ids
