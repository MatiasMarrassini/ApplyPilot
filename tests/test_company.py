import pandas as pd
import pytest

from applypilot.applications import application_dir, company_for_prompt
from applypilot.database import get_connection, init_db
from applypilot.discovery.jobspy import store_jobspy_results
from applypilot.scoring import scorer


@pytest.fixture
def conn():
    c = init_db()
    c.execute("DELETE FROM jobs")
    c.commit()
    return c


def frame(url, company):
    return pd.DataFrame([{"job_url": url, "title": "Backend Engineer", "company": company,
                          "location": "Buenos Aires", "site": "linkedin", "description": "short"}])


def company(url):
    return get_connection().execute("SELECT company FROM jobs WHERE url = ?", (url,)).fetchone()[0]


def test_jobspy_stores_company_and_backfills_old_rows(conn):
    assert store_jobspy_results(conn, frame("https://li/1", "Globant"), "x") == (1, 0)
    assert company("https://li/1") == "Globant"

    # A job stored before the column existed gets its company when seen again...
    conn.execute("INSERT INTO jobs (url, title, site) VALUES ('https://li/2', 'Old', 'linkedin')")
    conn.commit()
    assert store_jobspy_results(conn, frame("https://li/2", "Mercado Libre"), "x") == (0, 1)
    assert company("https://li/2") == "Mercado Libre"
    # ...but an existing company is never overwritten.
    store_jobspy_results(conn, frame("https://li/2", "Other"), "x")
    assert company("https://li/2") == "Mercado Libre"


def test_workday_rows_get_employer_as_company(conn):
    conn.execute("INSERT INTO jobs (url, site, strategy) VALUES ('https://wd/1', 'Netflix', 'workday_api')")
    conn.execute("INSERT INTO jobs (url, site, strategy) VALUES ('https://li/9', 'linkedin', 'jobspy')")
    conn.commit()
    init_db()
    assert company("https://wd/1") == "Netflix"
    assert company("https://li/9") is None  # a job board is not a company


def test_ai_gets_the_company_not_the_job_board(monkeypatch):
    sent = []

    class FakeClient:
        def chat(self, messages, **kwargs):
            sent.append(messages[-1]["content"])
            return "SCORE: 8\nKEYWORDS: x\nREASONING: ok"

    monkeypatch.setattr(scorer, "get_client", lambda: FakeClient())
    job = {"title": "Dev", "site": "linkedin", "company": "Globant", "full_description": "d"}
    scorer.score_job("resume", job)
    assert "COMPANY: Globant" in sent[0]

    scorer.score_job("resume", {**job, "company": None})
    assert "COMPANY: linkedin" not in sent[1] and "Not specified" in sent[1]


def test_folder_uses_company_when_known():
    job = {"url": "https://li/1", "site": "linkedin", "title": "Dev", "discovered_at": "2026-10-01"}
    assert "_Globant_Dev_" in application_dir({**job, "company": "Globant"}, create=False).name
    assert "_linkedin_Dev_" in application_dir(job, create=False).name
    assert company_for_prompt({"company": "  "}).startswith("Not specified")


def test_ui_shows_and_searches_company(conn):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from applypilot.ui.server import create_app

    conn.execute("INSERT INTO jobs (url, title, company, site) VALUES ('https://li/1', 'Dev', 'Globant', 'linkedin')")
    conn.execute("INSERT INTO jobs (url, title, site) VALUES ('https://li/2', 'Other', 'indeed')")
    conn.commit()
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    r = client.get("/jobs", params={"q": "globant"})
    assert "Globant" in r.text and "vía linkedin" in r.text and "Other" not in r.text
