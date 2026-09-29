"""One folder per job application, holding its tailored resume, cover letter and job copy.

    applications/2026-09-29_indeed_Senior_Data_Engineer_3f9a12c4/
        resume.txt  resume.pdf  cover_letter.txt  cover_letter.pdf  job.txt  tailor_report.json

The short hash of the job URL makes the name unique, so two postings with the
same title on the same site no longer overwrite each other's files.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import APPLICATIONS_DIR

RESUME_FILE = "resume.txt"
COVER_LETTER_FILE = "cover_letter.txt"
JOB_FILE = "job.txt"
TAILOR_REPORT_FILE = "tailor_report.json"


def _slug(text: str | None, max_len: int) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "")[:max_len].strip()
    return re.sub(r"\s+", "_", text) or "job"


def application_dir(job: dict, create: bool = True) -> Path:
    """Folder for one job's documents. Deterministic: same job, same folder."""
    day = (job.get("discovered_at") or datetime.now(timezone.utc).isoformat())[:10]
    digest = hashlib.sha1(job["url"].encode("utf-8")).hexdigest()[:8]
    folder = APPLICATIONS_DIR / f"{day}_{_slug(job.get('site'), 20)}_{_slug(job.get('title'), 50)}_{digest}"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder
