import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from applypilot.database import get_connection, init_db
from applypilot.ui.server import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def client():
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    # scores 1..9 plus one unscored job; job 3 is already discarded
    for n in range(1, 10):
        conn.execute("INSERT INTO jobs (url, title, site, fit_score, discovered_at) VALUES (?, ?, 'linkedin', ?, ?)",
                     (f"https://x/{n}", f"Job {n}", n, f"2026-09-{n:02d}T10:00:00"))
    conn.execute("INSERT INTO jobs (url, title, site) VALUES ('https://x/none', 'Unscored', 'indeed')")
    conn.execute("UPDATE jobs SET discarded_at = '2026-09-30' WHERE url = 'https://x/3'")
    conn.commit()
    return TestClient(create_app(), base_url="http://127.0.0.1")


def rowid(url):
    return get_connection().execute("SELECT rowid FROM jobs WHERE url = ?", (url,)).fetchone()[0]


def discarded():
    return {r[0] for r in get_connection().execute("SELECT url FROM jobs WHERE discarded_at IS NOT NULL")}


def test_score_band_filter(client):
    r = client.get("/jobs", params={"score": "mid"}, headers={"HX-Target": "results"})
    assert "Job 5" in r.text and "Job 6" in r.text
    assert "Job 4" not in r.text and "Job 7" not in r.text
    r = client.get("/jobs", params={"score": "none"}, headers={"HX-Target": "results"})
    assert "Unscored" in r.text and "Job 1" not in r.text


def test_bulk_discard_selected_ids_and_undo(client):
    ids = [rowid("https://x/1"), rowid("https://x/2"), rowid("https://x/3")]  # 3 was already discarded
    r = client.post("/jobs/bulk", data={"action": "discard", "ids": ids, "view": "pending"}, headers=HX)
    assert "2 ofertas descartadas" in r.text
    assert discarded() == {"https://x/1", "https://x/2", "https://x/3"}
    assert r.headers["HX-Trigger"] == "counts-changed"

    # Undo restores exactly the two it discarded, not job 3.
    changed = ",".join(str(i) for i in ids[:2])
    r = client.post("/jobs/bulk", data={"action": "restore", "ids_csv": changed, "undo": "1"}, headers=HX)
    assert "2 ofertas restauradas" in r.text and "Deshacer" not in r.text
    assert discarded() == {"https://x/3"}


def test_bulk_all_matching_uses_the_filters(client):
    # "Select all that match" on the 4-or-less band: jobs 1, 2, 4 (3 is already discarded)
    r = client.post("/jobs/bulk", data={"action": "discard", "all": "1", "view": "pending", "score": "low"}, headers=HX)
    assert "3 ofertas descartadas" in r.text
    assert discarded() == {"https://x/1", "https://x/2", "https://x/3", "https://x/4"}


def test_bulk_mark_applied_and_bad_action(client):
    r = client.post("/jobs/bulk", data={"action": "applied", "ids": [rowid("https://x/9")]}, headers=HX)
    assert "1 oferta marcada como aplicada" in r.text
    assert get_connection().execute("SELECT applied_at FROM jobs WHERE url = 'https://x/9'").fetchone()[0]
    assert client.post("/jobs/bulk", data={"action": "delete"}, headers=HX).status_code == 400
    assert client.post("/jobs/bulk", data={"action": "discard"}).status_code == 403  # no HX header


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Para revisar" in r.text and "Job 9" in r.text and "Job 6" not in r.text  # 7+ only
    assert 'class="pick"' not in r.text  # no bulk checkboxes on the home list
    job_id = rowid("https://x/9")
    r = client.post(f"/jobs/{job_id}/discard", data={"ctx": "home"}, headers=HX)
    assert "Descartada" in r.text and 'class="pick"' not in r.text
