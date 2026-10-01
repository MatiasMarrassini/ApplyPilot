"""Shared Jinja2 environment for the web UI."""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

from applypilot import __version__

UI_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=UI_DIR / "templates")
templates.env.globals["version"] = __version__
# Job URLs come from scraped sites: never render a non-http(s) link (e.g. javascript:).
templates.env.filters["http_url"] = lambda u: u if u and u.lower().startswith(("http://", "https://")) else "#"


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def ago(iso: str | None) -> str:
    """'hoy', 'ayer', 'hace 3 días' or a date, in the user's local time."""
    dt = _local(iso)
    if not dt:
        return "—"
    days = (datetime.now().astimezone().date() - dt.date()).days
    if days <= 0:
        return "hoy"
    if days == 1:
        return "ayer"
    if days < 7:
        return f"hace {days} días"
    return dt.strftime("%d/%m/%Y")


def clock(iso: str | None) -> str:
    """'hoy a las 13:10', 'ayer a las 9:05' or a date."""
    dt = _local(iso)
    if not dt:
        return ""
    when = ago(iso)
    return f"{when} a las {dt:%H:%M}" if when in ("hoy", "ayer") else when


def score_band(score) -> str:
    if score is None:
        return "none"
    return "high" if score >= 7 else "mid" if score >= 5 else "low"


def sidebar_state() -> dict:
    """Shown on every page: pending count, AI provider, and whether a run is going."""
    from applypilot.database import get_connection
    from applypilot.ui.runner import runner

    pending = get_connection().execute(
        "SELECT COUNT(*) FROM jobs WHERE discarded_at IS NULL AND applied_at IS NULL"
    ).fetchone()[0]
    if os.environ.get("LLM_URL"):
        provider = "Modelo local"
    elif os.environ.get("GEMINI_API_KEY"):
        provider = "Gemini"
    elif os.environ.get("OPENAI_API_KEY"):
        provider = "OpenAI"
    else:
        provider = ""
    run = runner.current
    return {
        "pending": pending,
        "provider": provider,
        "model": os.environ.get("LLM_MODEL", ""),
        "running": run.title if run and run.running else "",
    }


templates.env.filters["ago"] = ago
templates.env.filters["clock"] = clock
templates.env.filters["band"] = score_band
templates.env.globals["sidebar_state"] = sidebar_state
