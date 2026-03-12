import httpx

from app.services.linkedin_scraper import (
    detect_easy_apply,
    detect_modality,
    normalize_job_url,
    parse_applicant_count,
    request_with_retry,
)


def test_parse_applicant_count():
    count, raw = parse_applicant_count("Mas de 1.250 postulantes")
    assert count == 1250
    assert raw is not None


def test_parse_applicant_count_first_applicants_phrase():
    count, raw = parse_applicant_count("Be among the first 25 applicants")
    assert count == 25
    assert raw is not None


def test_parse_applicant_count_ignores_unrelated_numbers():
    count, raw = parse_applicant_count("3 years of experience required and 2 interviews")
    assert count == 0
    assert raw is None


def test_detect_modality():
    assert detect_modality("Remote role available") == "remote"
    assert detect_modality("Trabajo hibrido en Santiago") == "hybrid"


def test_detect_easy_apply():
    assert detect_easy_apply("Apply now with Easy Apply") is True


def test_normalize_job_url():
    normalized = normalize_job_url("www.linkedin.com/jobs/view/12345/?trk=feed")
    assert normalized == "https://www.linkedin.com/jobs/view/12345"


def test_request_with_retry_retries_transient_then_succeeds(monkeypatch):
    calls = {"count": 0}

    class FakeClient:
        def get(self, url):
            calls["count"] += 1
            req = httpx.Request("GET", url)
            if calls["count"] < 3:
                return httpx.Response(503, request=req)
            return httpx.Response(200, request=req, text="ok")

    monkeypatch.setattr("app.services.linkedin_scraper.time.sleep", lambda _: None)
    monkeypatch.setattr("app.services.linkedin_scraper.random.uniform", lambda *_: 0.0)

    response = request_with_retry(FakeClient(), "https://example.com")
    assert response is not None
    assert response.status_code == 200
    assert calls["count"] == 3


def test_request_with_retry_stops_on_non_transient_status(monkeypatch):
    calls = {"count": 0}

    class FakeClient:
        def get(self, url):
            calls["count"] += 1
            req = httpx.Request("GET", url)
            return httpx.Response(404, request=req)

    monkeypatch.setattr("app.services.linkedin_scraper.time.sleep", lambda _: None)

    response = request_with_retry(FakeClient(), "https://example.com")
    assert response is None
    assert calls["count"] == 1
