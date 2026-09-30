import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from applypilot import __version__
from applypilot.database import init_db
from applypilot.pipeline import _count_pending
from applypilot.ui import pipeline_routes
from applypilot.ui.runner import Runner
from applypilot.ui.server import create_app

HX = {"HX-Request": "true"}
LLM_KEYS = ["GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL"]


@pytest.fixture
def started(monkeypatch):
    """Capture runner.start calls instead of spawning the real pipeline."""
    calls = []
    fake = Runner()
    monkeypatch.setattr(fake, "start", lambda title, args: calls.append((title, args)))
    monkeypatch.setattr(pipeline_routes, "runner", fake)
    for key in LLM_KEYS:
        monkeypatch.delenv(key, raising=False)
    return calls


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_page_renders_and_locks_ai_stages_without_key(client, started):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Necesita una" in r.text  # AI stages locked

    r = client.post("/pipeline/run", data={"stages": ["score"]}, headers=HX)
    assert "necesitan una clave" in r.text
    r = client.post("/pipeline/run", data={}, headers=HX)
    assert "Elegí al menos una etapa" in r.text
    assert started == []


def test_preset_builds_cli_args(client, started, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    r = client.post("/pipeline/run", data={"preset": "find", "workers": "99", "min_score": "8",
                                           "validation": "bogus"}, headers=HX)
    assert r.headers.get("HX-Trigger") == "run-started"
    assert started == [("Buscar ofertas nuevas", [
        "run", "discover", "enrich", "--min-score", "8", "--workers", "8", "--validation", "normal",
    ])]

    client.post("/pipeline/run", data={"stages": ["pdf", "score"]}, headers=HX)
    assert started[1][1][:3] == ["run", "score", "pdf"]  # canonical order


def test_runner_captures_real_subprocess_output(tmp_path):
    runner = Runner()
    run = runner.start("version", ["--version"])
    with pytest.raises(RuntimeError):
        runner.start("second", ["--version"])  # one run at a time
    deadline = time.time() + 60
    while run.running and time.time() < deadline:
        time.sleep(0.1)
    assert run.status == "ok"
    assert any(__version__ in line for line in run.lines)
    with open(run.log_path, encoding="utf-8") as f:
        assert __version__ in f.read()


def test_streaming_pending_counts_ignore_discarded_jobs():
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    conn.execute("INSERT INTO jobs (url, full_description, discarded_at) VALUES ('https://x/1', 'd', '2026-09-29')")
    conn.commit()
    # Otherwise `applypilot run --stream` would loop forever on a job no stage will process.
    assert _count_pending("score") == 0
    assert _count_pending("enrich") == 0


def test_run_env_picks_up_env_file_edits(monkeypatch):
    from applypilot import config
    from applypilot.ui.runner import _child_env

    monkeypatch.setenv("LLM_MODEL", "old-model-loaded-at-startup")
    config.ENV_PATH.write_text("LLM_MODEL=new-model\n", encoding="utf-8")
    try:
        assert _child_env()["LLM_MODEL"] == "new-model"
    finally:
        config.ENV_PATH.unlink()
