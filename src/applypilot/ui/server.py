"""FastAPI app for the local web UI.

Only meant to be served on 127.0.0.1: it exposes personal data (resume,
profile) and, later, API keys.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from applypilot import __version__
from applypilot.config import ensure_dirs, load_env
from applypilot.database import init_db
from applypilot.ui import jobs

UI_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=UI_DIR / "templates")
templates.env.globals["version"] = __version__
# Job URLs come from scraped sites: never render a non-http(s) link (e.g. javascript:).
templates.env.filters["http_url"] = lambda u: u if u and u.lower().startswith(("http://", "https://")) else "#"

ACTIONS = {
    "discard": jobs.discard,
    "restore": jobs.restore,
    "applied": jobs.mark_applied,
    "unapply": jobs.unmark_applied,
}


def create_app() -> FastAPI:
    load_env()
    ensure_dirs()
    init_db()

    app = FastAPI(title="ApplyPilot", docs_url=None, redoc_url=None, openapi_url=None)
    # Reject requests whose Host isn't local (DNS-rebinding protection).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")

    @app.middleware("http")
    async def require_htmx_for_writes(request: Request, call_next):
        # Browsers can't send custom headers cross-origin without a CORS
        # preflight (which we never approve), so this blocks CSRF from other sites.
        if request.method == "POST" and request.headers.get("HX-Request") != "true":
            return HTMLResponse("Forbidden", status_code=403)
        return await call_next(request)

    @app.get("/")
    def index():
        return RedirectResponse("/jobs")

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(
        request: Request,
        view: str = "pending",
        q: str = "",
        site: str = "",
        min_score: str = "",
        sort: str = "score",
        page: int = 1,
    ):
        score = int(min_score) if min_score.isdigit() else None
        items, total = jobs.list_jobs(view, q.strip(), site, score, sort, page)
        ctx = {
            "jobs": items,
            "total": total,
            "page": page,
            "pages": max(1, -(-total // jobs.PAGE_SIZE)),
            "filters": {"view": view, "q": q, "site": site, "min_score": min_score, "sort": sort},
            "views": jobs.VIEWS,
            "sorts": jobs.SORTS,
            "counts": jobs.view_counts(),
            "sites": jobs.list_sites(),
            "nav": "jobs",
        }
        # HTMX filter changes only need the results block re-rendered.
        name = "jobs/_results.html" if request.headers.get("HX-Target") == "results" else "jobs/list.html"
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/jobs/counts", response_class=HTMLResponse)
    def job_counts(request: Request):
        return templates.TemplateResponse(request, "jobs/_counts.html", {"counts": jobs.view_counts()})

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int):
        job = _get_or_404(job_id)
        return templates.TemplateResponse(
            request, "jobs/detail.html",
            {"job": job, "docs": jobs.job_documents(job), "nav": "jobs"},
        )

    @app.post("/jobs/{job_id}/{action}", response_class=HTMLResponse)
    def job_action(request: Request, job_id: int, action: str, ctx: str = Form("row")):
        if action not in ACTIONS:
            raise HTTPException(404)
        _get_or_404(job_id)
        ACTIONS[action](job_id)
        job = jobs.get_job(job_id)
        name = "jobs/_actions.html" if ctx == "detail" else "jobs/_row.html"
        response = templates.TemplateResponse(request, name, {"job": job})
        response.headers["HX-Trigger"] = "counts-changed"  # list page refreshes its tab counts
        return response

    @app.get("/jobs/{job_id}/{kind}.pdf")
    def job_pdf(job_id: int, kind: str):
        job = _get_or_404(job_id)
        path = jobs.document_pdf_path(job, kind)
        if not path:
            raise HTTPException(404, "PDF no disponible")
        return FileResponse(path, media_type="application/pdf", filename=path.name,
                            content_disposition_type="inline")

    return app


def _get_or_404(job_id: int) -> dict:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Oferta no encontrada")
    return job


def serve(port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"ApplyPilot UI en {url}  (Ctrl+C para detener)")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
