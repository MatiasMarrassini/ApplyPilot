"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. All personal data is loaded at runtime from the user's
profile and resume file.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

from applypilot.applications import company_for_prompt
from applypilot.config import RESUME_PATH, load_profile
from applypilot.database import get_connection, get_jobs_by_stage
from applypilot.llm import get_client

log = logging.getLogger(__name__)

# Stop the run after this many LLM failures in a row: it's a config problem
# (bad model name, invalid key), not a flaky job, so don't burn through the queue.
MAX_CONSECUTIVE_ERRORS = 3


# ── Scoring Prompt ────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a job fit evaluator. Given a candidate's resume and a job description, score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required skills and qualifications.
- 7-8: Strong match. Candidate has most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Candidate has some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, would need substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (programming languages, frameworks, tools)
- Consider transferable experience (automation, scripting, API work)
- Factor in the candidate's project experience
- Be realistic about experience level vs. job requirements (years of experience, seniority)

LOCATION AND WORK ELIGIBILITY (check this before the skills score, using CANDIDATE LOCATION below):
- Remote open to the candidate's country, to their region (e.g. Latin America) or worldwide: no penalty.
- Remote restricted to a country or region where the candidate does not live ("US only", "must reside in the EU",
  US/EU citizenship, security clearance, local work authorization, or no visa sponsorship when the candidate would need it):
  score at most 3 and say so in the reasoning.
- Onsite or hybrid in a city or country where the candidate does not live: score at most 4, unless relocation support is offered.
- When the posting doesn't say where the hire must be, don't penalize.

Write KEYWORDS and REASONING in {reasoning_language}. Keep technology and tool names as they appear in the posting.

RESPOND IN EXACTLY THIS FORMAT (no other text, keep these English labels):
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job description that match or could match the candidate]
REASONING: [2-3 sentences explaining the score]"""

# The web UI is in Spanish, so the score explanation shown there is too.
REASONING_LANGUAGE = "Spanish"


def _candidate_location(profile: dict | None) -> str:
    """One line telling the model where the candidate lives and can legally work."""
    if not profile:
        return "Unknown (do not apply location penalties)."
    personal = profile.get("personal") or {}
    auth = profile.get("work_authorization") or {}
    place = ", ".join(p for p in (personal.get("city"), personal.get("province_state"), personal.get("country")) if p)
    parts = [f"Lives in {place}." if place else "Location not given."]
    if auth.get("work_permit_type"):
        parts.append(f"Work permit: {auth['work_permit_type']}.")
    if auth.get("require_sponsorship") not in (None, ""):
        parts.append(f"Needs visa sponsorship to work abroad: {auth['require_sponsorship']}.")
    return " ".join(parts)


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    score = 0
    keywords = ""
    reasoning = response

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    return {"score": score, "keywords": keywords, "reasoning": reasoning}


def score_job(resume_text: str, job: dict, profile: dict | None = None) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.
        profile: User profile, used for the candidate's location and work eligibility.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {company_for_prompt(job)}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    messages = [
        {"role": "system", "content": SCORE_PROMPT.replace("{reasoning_language}", REASONING_LANGUAGE)},
        {"role": "user", "content": (
            f"CANDIDATE LOCATION: {_candidate_location(profile)}\n\n"
            f"RESUME:\n{resume_text}\n\n---\n\nJOB POSTING:\n{job_text}"
        )},
    ]

    try:
        client = get_client()
        response = client.chat(messages, max_tokens=512, temperature=0.2)
        return _parse_score_response(response)
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {"score": 0, "keywords": "", "reasoning": f"LLM error: {e}", "error": str(e)}


def run_scoring(limit: int = 0, rescore: bool = False) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list}
    """
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    try:
        profile = load_profile()
    except FileNotFoundError:
        profile = None  # scoring still works, just without location rules
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d jobs sequentially...", len(jobs))
    t0 = time.time()
    completed = 0
    errors = 0
    results: list[dict] = []

    consecutive_errors = 0
    last_error = ""
    for job in jobs:
        result = score_job(resume_text, job, profile)
        result["url"] = job["url"]
        completed += 1

        if result.get("error"):
            errors += 1
            consecutive_errors += 1
            last_error = result["error"]
            log.info("[%d/%d] ERROR  %s", completed, len(jobs), job.get("title", "?")[:60])
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.error("Stopping scoring after %d failed LLM calls in a row. Last error: %s",
                          consecutive_errors, last_error)
                break
            continue

        consecutive_errors = 0
        results.append(result)
        log.info(
            "[%d/%d] score=%d  %s",
            completed, len(jobs), result["score"], job.get("title", "?")[:60],
        )

    # Write scores to DB. Failed calls are not written, so those jobs stay
    # unscored and get retried on the next run instead of being stuck at 0.
    now = datetime.now(timezone.utc).isoformat()
    for r in results:
        conn.execute(
            "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (r["score"], f"{r['keywords']}\n{r['reasoning']}", now, r["url"]),
        )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Done: %d scored in %.1fs (%.1f jobs/sec)", len(results), elapsed, len(results) / elapsed if elapsed > 0 else 0)

    # Score distribution
    dist = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        raise RuntimeError(f"LLM calls are failing: {last_error}")

    return {
        "scored": len(results),
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
    }
