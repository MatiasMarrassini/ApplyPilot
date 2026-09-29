"""Job queries and user actions for the web UI.

Jobs are addressed by SQLite ``rowid`` in URLs because the primary key
(the job URL) is awkward to put in a path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from applypilot.database import get_connection

PAGE_SIZE = 50

# View name -> (label, SQL condition)
VIEWS: dict[str, tuple[str, str]] = {
    "pending": ("Pendientes", "discarded_at IS NULL AND applied_at IS NULL"),
    "ready": (
        "Listas para aplicar",
        "discarded_at IS NULL AND applied_at IS NULL AND tailored_resume_path IS NOT NULL",
    ),
    "applied": ("Aplicadas", "applied_at IS NOT NULL"),
    "discarded": ("Descartadas", "discarded_at IS NOT NULL"),
    "all": ("Todas", "1=1"),
}

SORTS: dict[str, tuple[str, str]] = {
    "score": ("Puntaje", "fit_score DESC NULLS LAST, discovered_at DESC"),
    "recent": ("Más recientes", "discovered_at DESC"),
    "title": ("Puesto", "title COLLATE NOCASE ASC"),
}


def job_status(job: dict) -> tuple[str, str]:
    """Return (label, css_class) describing where a job is in the pipeline."""
    if job.get("discarded_at"):
        return "Descartada", "discarded"
    if job.get("applied_at") or job.get("apply_status") == "applied":
        return "Aplicada", "applied"
    if job.get("apply_status") == "in_progress":
        return "Aplicando…", "progress"
    if job.get("apply_status") == "manual":
        return "Aplicar a mano", "warn"
    if job.get("apply_error"):
        return "Error al aplicar", "error"
    if job.get("tailored_resume_path"):
        return "Lista", "ready"
    if job.get("fit_score") is not None:
        return "Puntuada", "scored"
    if job.get("full_description"):
        return "Con descripción", "new"
    return "Nueva", "new"


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["status_label"], job["status_class"] = job_status(job)
    return job


def list_jobs(
    view: str = "pending",
    q: str = "",
    site: str = "",
    min_score: int | None = None,
    sort: str = "score",
    page: int = 1,
) -> tuple[list[dict], int]:
    """Return one page of jobs matching the filters, plus the total match count."""
    conditions = [VIEWS.get(view, VIEWS["pending"])[1]]
    params: list = []

    if q:
        conditions.append("(title LIKE ? OR site LIKE ? OR location LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if site:
        conditions.append("site = ?")
        params.append(site)
    if min_score is not None:
        conditions.append("fit_score >= ?")
        params.append(min_score)

    where = " AND ".join(conditions)
    order = SORTS.get(sort, SORTS["score"])[1]
    conn = get_connection()

    total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT rowid AS id, * FROM jobs WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, (max(page, 1) - 1) * PAGE_SIZE],
    ).fetchall()
    return [_row_to_job(r) for r in rows], total


def view_counts() -> dict[str, int]:
    conn = get_connection()
    return {
        name: conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {cond}").fetchone()[0]
        for name, (_, cond) in VIEWS.items()
    }


def list_sites() -> list[str]:
    rows = get_connection().execute(
        "SELECT DISTINCT site FROM jobs WHERE site IS NOT NULL ORDER BY site COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


def get_job(job_id: int) -> dict | None:
    row = get_connection().execute(
        "SELECT rowid AS id, * FROM jobs WHERE rowid = ?", (job_id,)
    ).fetchone()
    return _row_to_job(row) if row else None


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        return None


def job_documents(job: dict) -> dict:
    """Load the tailored CV and cover letter (text + whether a PDF exists)."""
    docs = {}
    for key, column in (("cv", "tailored_resume_path"), ("cover", "cover_letter_path")):
        path = job.get(column)
        docs[key] = {
            "text": _read_text(path),
            "has_pdf": bool(path) and Path(path).with_suffix(".pdf").exists(),
        }
    return docs


def documents_folder(job: dict) -> Path | None:
    """Folder holding this job's CV/letter, if they've been generated."""
    for column in ("tailored_resume_path", "cover_letter_path"):
        if job.get(column):
            folder = Path(job[column]).parent
            if folder.is_dir():
                return folder
    return None


def open_in_file_manager(folder: Path) -> None:
    """Open a folder in Explorer/Finder. The server runs on the user's machine."""
    import os
    import subprocess
    import sys

    if sys.platform == "win32":
        os.startfile(folder)  # local UI; the path comes from our own DB
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def document_pdf_path(job: dict, kind: str) -> Path | None:
    column = {"cv": "tailored_resume_path", "cover": "cover_letter_path"}.get(kind)
    path = job.get(column) if column else None
    if not path:
        return None
    pdf = Path(path).with_suffix(".pdf")
    return pdf if pdf.exists() else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update(job_id: int, sql: str, params: tuple = ()) -> None:
    conn = get_connection()
    conn.execute(f"UPDATE jobs SET {sql} WHERE rowid = ?", params + (job_id,))
    conn.commit()


def discard(job_id: int) -> None:
    _update(job_id, "discarded_at = ?", (_now(),))


def restore(job_id: int) -> None:
    _update(job_id, "discarded_at = NULL")


def mark_applied(job_id: int) -> None:
    # Same fields as apply.launcher.mark_job(..., "applied")
    _update(
        job_id,
        "apply_status = 'applied', applied_at = ?, apply_error = NULL, agent_id = NULL",
        (_now(),),
    )


def unmark_applied(job_id: int) -> None:
    _update(job_id, "apply_status = NULL, applied_at = NULL")
