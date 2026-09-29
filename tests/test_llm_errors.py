import httpx
import pytest

from applypilot import config
from applypilot.database import get_connection, init_db
from applypilot.llm import LLMClient, LLMError, _error_detail, resolve_provider
from applypilot.scoring import scorer


def test_error_detail_extracts_provider_message():
    # Shape returned by Gemini's OpenAI-compatible endpoint for an unknown model
    resp = httpx.Response(400, json=[{"error": {"code": 400, "message": "Model not found: Gemini 3.1 Flash Lite"}}])
    assert _error_detail(resp) == "Model not found: Gemini 3.1 Flash Lite"
    assert _error_detail(httpx.Response(401, json={"error": {"message": "Invalid key"}})) == "Invalid key"
    assert _error_detail(httpx.Response(500, text="boom")) == "boom"


def test_chat_raises_llm_error_with_detail():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "bad model name"}})

    client = LLMClient("http://llm.test/v1", "x", "k", max_retries=1)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="HTTP 400: bad model name"):
        client.chat([{"role": "user", "content": "hi"}])


def test_resolve_provider_uses_given_values_not_environment():
    base, model, key = resolve_provider({"OPENAI_API_KEY": "sk", "LLM_MODEL": "gpt-x"})
    assert base == "https://api.openai.com/v1" and model == "gpt-x" and key == "sk"


@pytest.fixture
def jobs_db(monkeypatch):
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    for i in range(5):
        conn.execute("INSERT INTO jobs (url, title, site, full_description) VALUES (?, ?, 's', 'd')",
                     (f"https://x/{i}", f"Job {i}"))
    conn.commit()
    config.RESUME_PATH.write_text("resume", encoding="utf-8")
    monkeypatch.setattr(scorer, "RESUME_PATH", config.RESUME_PATH)
    return conn


def test_scoring_stops_after_repeated_failures_and_keeps_jobs_unscored(jobs_db, monkeypatch):
    calls = []

    def failing(resume, job):
        calls.append(job["url"])
        return {"score": 0, "keywords": "", "reasoning": "LLM error: x", "error": "HTTP 400: bad model"}

    monkeypatch.setattr(scorer, "score_job", failing)
    with pytest.raises(RuntimeError, match="bad model"):
        scorer.run_scoring()
    assert len(calls) == scorer.MAX_CONSECUTIVE_ERRORS  # didn't burn through all 5
    assert get_connection().execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0] == 0


def test_occasional_failure_is_skipped_not_saved_as_zero(jobs_db, monkeypatch):
    def flaky(resume, job):
        if job["url"].endswith("/2"):
            return {"score": 0, "keywords": "", "reasoning": "LLM error: x", "error": "timeout"}
        return {"score": 8, "keywords": "py", "reasoning": "ok"}

    monkeypatch.setattr(scorer, "score_job", flaky)
    result = scorer.run_scoring()
    assert result["scored"] == 4 and result["errors"] == 1
    row = get_connection().execute("SELECT fit_score FROM jobs WHERE url = 'https://x/2'").fetchone()
    assert row[0] is None  # retried next run


def test_init_db_clears_fake_zero_scores(jobs_db):
    jobs_db.execute("UPDATE jobs SET fit_score = 0, score_reasoning = '\nLLM error: 400' WHERE url = 'https://x/0'")
    jobs_db.execute("UPDATE jobs SET fit_score = 3, score_reasoning = 'real' WHERE url = 'https://x/1'")
    jobs_db.commit()
    init_db()
    rows = dict(get_connection().execute("SELECT url, fit_score FROM jobs WHERE url IN ('https://x/0', 'https://x/1')"))
    assert rows == {"https://x/0": None, "https://x/1": 3}
