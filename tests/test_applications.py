import json
from pathlib import Path

import pytest

from applypilot import config
from applypilot.applications import application_dir
from applypilot.database import get_connection, init_db
from applypilot.scoring import cover_letter, pdf, tailor

SAME = {"site": "indeed", "title": "Senior Data Engineer", "discovered_at": "2026-09-29T10:00:00"}


def test_application_dir_is_unique_and_stable():
    a = application_dir({**SAME, "url": "https://x/1"}, create=False)
    b = application_dir({**SAME, "url": "https://x/2"}, create=False)
    assert a != b  # same title + site used to collide
    assert a == application_dir({**SAME, "url": "https://x/1"}, create=False)
    assert a.parent == config.APPLICATIONS_DIR
    assert a.name.startswith("2026-09-29_indeed_Senior_Data_Engineer_")


@pytest.fixture
def two_same_title_jobs(monkeypatch):
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    for url in ("https://x/1", "https://x/2"):
        conn.execute(
            "INSERT INTO jobs (url, title, site, fit_score, full_description, discovered_at) VALUES (?, ?, ?, 9, 'd', ?)",
            (url, SAME["title"], SAME["site"], SAME["discovered_at"]),
        )
    conn.commit()
    config.RESUME_PATH.write_text("base resume", encoding="utf-8")
    config.PROFILE_PATH.write_text(json.dumps({"personal": {"full_name": "A"}}), encoding="utf-8")
    for mod in (tailor, cover_letter):
        monkeypatch.setattr(mod, "RESUME_PATH", config.RESUME_PATH)
    # Skip real PDF rendering (headless Chrome); write a marker file instead.
    fake_pdf = lambda txt, *a, **k: Path(txt).with_suffix(".pdf").write_bytes(b"%PDF") or Path(txt).with_suffix(".pdf")
    monkeypatch.setattr(pdf, "convert_to_pdf", fake_pdf)
    monkeypatch.setattr(tailor, "tailor_resume",
                        lambda resume, job, profile, validation_mode="normal": (
                            f"CV for {job['url']}", {"status": "approved", "attempts": 1}))
    monkeypatch.setattr(cover_letter, "generate_cover_letter",
                        lambda resume, job, profile, validation_mode="normal": f"Letter for {job['url']}")
    return conn


def test_tailor_and_cover_write_into_one_folder_per_job(two_same_title_jobs):
    tailor.run_tailoring(min_score=7)
    cover_letter.run_cover_letters(min_score=7)

    rows = get_connection().execute(
        "SELECT url, tailored_resume_path, cover_letter_path FROM jobs ORDER BY url").fetchall()
    folders = set()
    for url, resume, letter in rows:
        resume, letter = Path(resume), Path(letter)
        assert resume.parent == letter.parent  # CV and letter side by side
        assert resume.read_text(encoding="utf-8") == f"CV for {url}"  # not overwritten by the other job
        assert letter.read_text(encoding="utf-8") == f"Letter for {url}"
        assert (resume.parent / "job.txt").exists() and resume.with_suffix(".pdf").exists()
        folders.add(resume.parent)
    assert len(folders) == 2


def test_batch_convert_uses_db_paths_including_cover_letters(two_same_title_jobs, tmp_path):
    legacy = tmp_path / "legacy_CL.txt"
    legacy.write_text("old letter", encoding="utf-8")
    two_same_title_jobs.execute(
        "UPDATE jobs SET tailored_resume_path = ?, cover_letter_path = ? WHERE url = 'https://x/1'",
        (str(tmp_path / "missing.txt"), str(legacy)),
    )
    two_same_title_jobs.commit()
    assert pdf.batch_convert() == 1
    assert legacy.with_suffix(".pdf").exists()


def test_open_folder_route(two_same_title_jobs, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from applypilot.ui import jobs as ui_jobs
    from applypilot.ui.server import create_app

    opened = []
    monkeypatch.setattr(ui_jobs, "open_in_file_manager", opened.append)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    job_id = get_connection().execute("SELECT rowid FROM jobs WHERE url = 'https://x/1'").fetchone()[0]

    r = client.post(f"/jobs/{job_id}/open-folder", headers={"HX-Request": "true"})
    assert "Todavía no hay documentos" in r.text and opened == []

    tailor.run_tailoring(min_score=7)
    assert "Abrir carpeta" in client.get(f"/jobs/{job_id}").text
    client.post(f"/jobs/{job_id}/open-folder", headers={"HX-Request": "true"})
    assert opened == [application_dir({**SAME, "url": "https://x/1"}, create=False)]
