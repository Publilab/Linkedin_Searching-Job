from app.services.matcher import compute_match


def test_matcher_returns_weighted_score_and_breakdown():
    profile = {
        "skills": ["Python", "SQL", "Docker"],
        "experience": ["Data Analyst", "Business Analyst"],
        "education": ["Bachelor Computer Science"],
    }
    job = {
        "title": "Data Analyst",
        "description": "Looking for Python and SQL analyst with Docker and BI experience",
    }

    score, breakdown = compute_match(profile, job)

    assert score > 0
    assert breakdown["skills"] >= 0
    assert isinstance(breakdown["matched_skills"], list)
