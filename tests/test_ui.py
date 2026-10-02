import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from applypilot.config import APP_DIR
from applypilot.database import get_connection, get_jobs_by_stage, init_db
from applypilot.ui.server import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def db():
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    conn.commit()
    return conn


def add_job(conn, url, title="Engineer", site="Acme", score=None, **extra):
    cols = {"url": url, "title": title, "site": site, "fit_score": score,
            "full_description": "desc", "discovered_at": "2026-09-29T10:00:00", **extra}
    conn.execute(
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        list(cols.values()),
    )
    conn.commit()
    return conn.execute("SELECT rowid FROM jobs WHERE url = ?", (url,)).fetchone()[0]


@pytest.fixture
def client(db):
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_list_filters_and_views(client, db):
    add_job(db, "https://a/1", title="Python Dev", score=9)
    add_job(db, "https://a/2", title="Java Dev", score=4)
    add_job(db, "https://a/3", title="Old", score=8, applied_at="2026-09-01")

    r = client.get("/jobs")
    assert r.status_code == 200
    assert "Python Dev" in r.text and "Java Dev" in r.text
    assert "Old" not in r.text  # applied jobs aren't pending

    r = client.get("/jobs", params={"min_score": "7"}, headers={"HX-Target": "results"})
    assert "Python Dev" in r.text and "Java Dev" not in r.text
    assert "<html" not in r.text  # partial only

    r = client.get("/jobs", params={"view": "applied"})
    assert "Old" in r.text and "Python Dev" not in r.text


def test_discard_restore_and_applied(client, db):
    job_id = add_job(db, "https://a/1", score=9)

    r = client.post(f"/jobs/{job_id}/discard", headers=HX)
    assert r.status_code == 200 and "Descartada" in r.text
    row = get_connection().execute("SELECT discarded_at FROM jobs WHERE rowid=?", (job_id,)).fetchone()
    assert row[0] is not None

    client.post(f"/jobs/{job_id}/restore", headers=HX)
    r = client.post(f"/jobs/{job_id}/applied", data={"ctx": "detail"}, headers=HX)
    assert 'id="actions"' in r.text and "Aplicada" in r.text
    row = get_connection().execute(
        "SELECT discarded_at, apply_status, applied_at FROM jobs WHERE rowid=?", (job_id,)
    ).fetchone()
    assert row[0] is None and row[1] == "applied" and row[2] is not None


def test_discarded_jobs_are_skipped_by_pipeline(db):
    add_job(db, "https://a/keep")
    add_job(db, "https://a/drop", discarded_at="2026-09-29")
    pending = [j["url"] for j in get_jobs_by_stage(conn=db, stage="pending_score")]
    assert pending == ["https://a/keep"]


def test_post_without_htmx_header_is_rejected(client, db):
    job_id = add_job(db, "https://a/1")
    assert client.post(f"/jobs/{job_id}/discard").status_code == 403


def test_foreign_host_is_rejected(db):
    c = TestClient(create_app(), base_url="http://evil.example")
    assert c.get("/jobs").status_code == 400


def test_detail_shows_documents_and_blocks_js_urls(client, db):
    cv = APP_DIR / "cv_test.txt"
    cv.write_text("MY TAILORED CV", encoding="utf-8")
    job_id = add_job(db, "javascript:alert(1)", score=8, tailored_resume_path=str(cv),
                     score_reasoning="python, sql\nGood match.")
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    assert "MY TAILORED CV" in r.text and "Good match." in r.text
    assert 'href="javascript:' not in r.text
    assert client.get(f"/jobs/{job_id}/cv.pdf").status_code == 404
    assert client.get("/jobs/99999").status_code == 404


def test_static_assets_are_versioned(client):
    import re

    html = client.get("/jobs").text
    for asset in ("app.css", "app.js", "vendor/htmx.min.js"):
        m = re.search(rf'/static/{re.escape(asset)}\?v=(\d+)', html)
        assert m and int(m.group(1)) > 0, asset
    assert client.get("/static/app.css?v=123").status_code == 200
