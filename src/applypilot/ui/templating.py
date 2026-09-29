"""Shared Jinja2 environment for the web UI."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from applypilot import __version__

UI_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=UI_DIR / "templates")
templates.env.globals["version"] = __version__
# Job URLs come from scraped sites: never render a non-http(s) link (e.g. javascript:).
templates.env.filters["http_url"] = lambda u: u if u and u.lower().startswith(("http://", "https://")) else "#"
