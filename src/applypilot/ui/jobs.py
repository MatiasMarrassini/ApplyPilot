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
    "score": ("Mejor puntaje primero", "fit_score DESC NULLS LAST, discovered_at DESC"),
    "recent": ("Más recientes", "discovered_at DESC"),
    "company": ("Empresa", "COALESCE(company, site) COLLATE NOCASE ASC, fit_score DESC"),
    "title": ("Puesto", "title COLLATE NOCASE ASC"),
}

# Same bands as the score colors (green / amber / red).
SCORE_BANDS: dict[str, tuple[str, str]] = {
    "high": ("7 o más", "fit_score >= 7"),
    "mid": ("5 y 6", "fit_score BETWEEN 5 AND 6"),
    "low": ("4 o menos", "fit_score <= 4"),
    "none": ("Sin puntuar", "fit_score IS NULL"),
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
        return "CV listo", "ready"
    if job.get("fit_score") is not None:
        return "Puntuada", "scored"
    if job.get("full_description"):
        return "Con descripción", "new"
    return "Nueva", "new"


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["status_label"], job["status_class"] = job_status(job)
    return job


def _where(view: str = "pending", q: str = "", site: str = "", min_score: int | None = None,
           score_band: str = "") -> tuple[str, list]:
    """SQL condition for a set of list filters. Shared by the list and bulk actions,
    so "select all N that match" acts on exactly what the list shows."""
    conditions = [VIEWS.get(view, VIEWS["pending"])[1]]
    params: list = []
    if q:
        conditions.append("(title LIKE ? OR company LIKE ? OR site LIKE ? OR location LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if site:
        conditions.append("site = ?")
        params.append(site)
    if min_score is not None:
        conditions.append("fit_score >= ?")
        params.append(min_score)
    if score_band in SCORE_BANDS:
        conditions.append(SCORE_BANDS[score_band][1])
    return " AND ".join(conditions), params


def list_jobs(
    view: str = "pending",
    q: str = "",
    site: str = "",
    min_score: int | None = None,
    sort: str = "score",
    page: int = 1,
    score_band: str = "",
) -> tuple[list[dict], int]:
    """Return one page of jobs matching the filters, plus the total match count."""
    where, params = _where(view, q, site, min_score, score_band)
    order = SORTS.get(sort, SORTS["score"])[1]
    conn = get_connection()

    total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT rowid AS id, * FROM jobs WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, (max(page, 1) - 1) * PAGE_SIZE],
    ).fetchall()
    return [_row_to_job(r) for r in rows], total


def matching_ids(view: str = "pending", q: str = "", site: str = "", min_score: int | None = None,
                 score_band: str = "") -> list[int]:
    where, params = _where(view, q, site, min_score, score_band)
    return [r[0] for r in get_connection().execute(f"SELECT rowid FROM jobs WHERE {where}", params)]


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


# --- Bulk actions ------------------------------------------------------------
# Each action only touches jobs where it changes something, and returns those
# ids, so "undo" reverts exactly what was changed.
BULK: dict[str, tuple[str, str, str]] = {
    # action: (SET clause, only-where condition, inverse action)
    "discard": ("discarded_at = :now", "discarded_at IS NULL", "restore"),
    "restore": ("discarded_at = NULL", "discarded_at IS NOT NULL", "discard"),
    "applied": ("apply_status = 'applied', applied_at = :now, apply_error = NULL, agent_id = NULL",
                "applied_at IS NULL", "unapply"),
    "unapply": ("apply_status = NULL, applied_at = NULL", "applied_at IS NOT NULL", "applied"),
}
BULK_DONE = {"discard": "descartada", "restore": "restaurada", "applied": "marcada como aplicada",
             "unapply": "desmarcada"}


def bulk_update(action: str, ids: list[int]) -> list[int]:
    """Apply a bulk action; returns the ids it actually changed."""
    set_sql, only, _ = BULK[action]
    if not ids:
        return []
    conn = get_connection()
    changed: list[int] = []
    for start in range(0, len(ids), 500):  # stay under SQLite's variable limit
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        changed += [r[0] for r in conn.execute(
            f"SELECT rowid FROM jobs WHERE rowid IN ({marks}) AND {only}", chunk)]
    for start in range(0, len(changed), 500):
        chunk = changed[start:start + 500]
        named = {f"i{n}": v for n, v in enumerate(chunk)}
        conn.execute(
            f"UPDATE jobs SET {set_sql} WHERE rowid IN ({','.join(':' + k for k in named)})",
            {"now": _now(), **named},
        )
    conn.commit()
    return changed


# --- Home ------------------------------------------------------------------

def home_stats(min_score: int) -> dict:
    conn = get_connection()
    one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]
    active = "discarded_at IS NULL"
    return {
        "found": one("SELECT COUNT(*) FROM jobs"),
        "scored": one(f"SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL AND {active}"),
        "unscored": one(f"SELECT COUNT(*) FROM jobs WHERE fit_score IS NULL AND full_description IS NOT NULL AND {active}"),
        "good": one(f"SELECT COUNT(*) FROM jobs WHERE fit_score >= ? AND {active}", min_score),
        "good_pending": one(f"SELECT COUNT(*) FROM jobs WHERE fit_score >= ? AND {active} AND applied_at IS NULL", min_score),
        "tailored": one(f"SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND {active}"),
        "applied": one("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL"),
        "applied_week": one("SELECT COUNT(*) FROM jobs WHERE applied_at >= datetime('now', '-7 days')"),
        "discarded": one("SELECT COUNT(*) FROM jobs WHERE discarded_at IS NOT NULL"),
        "last_found": one("SELECT MAX(discovered_at) FROM jobs"),
        "sources": [r[0] for r in conn.execute(
            "SELECT site FROM jobs GROUP BY site ORDER BY COUNT(*) DESC LIMIT 3")],
    }


def to_review(min_score: int, limit: int = 5) -> list[dict]:
    rows = get_connection().execute(
        "SELECT rowid AS id, * FROM jobs WHERE discarded_at IS NULL AND applied_at IS NULL "
        "AND fit_score >= ? ORDER BY fit_score DESC, discovered_at DESC LIMIT ?", (min_score, limit),
    ).fetchall()
    return [_row_to_job(r) for r in rows]
