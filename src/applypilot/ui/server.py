"""FastAPI app for the local web UI.

Only meant to be served on 127.0.0.1: it exposes personal data (resume,
profile) and API keys.
"""

from __future__ import annotations

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from applypilot import config
from applypilot.config import ensure_dirs, load_env
from applypilot.database import init_db
from applypilot.ui import jobs
from applypilot.ui.pipeline_routes import router as pipeline_router
from applypilot.ui.setup_routes import router as setup_router
from applypilot.ui.templating import UI_DIR, templates

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
    app.include_router(setup_router)
    app.include_router(pipeline_router)

    @app.middleware("http")
    async def require_htmx_for_writes(request: Request, call_next):
        # Browsers can't send custom headers cross-origin without a CORS
        # preflight (which we never approve), so this blocks CSRF from other sites.
        if request.method == "POST" and request.headers.get("HX-Request") != "true":
            return HTMLResponse("Forbidden", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        min_score = config.DEFAULTS["min_score"]
        return templates.TemplateResponse(request, "home.html", {
            "nav": "home",
            "stats": jobs.home_stats(min_score),
            "review": jobs.to_review(min_score),
            "min_score": min_score,
            "greeting": _greeting(),
            "last_run": _last_run(),
        })

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(
        request: Request,
        view: str = "pending",
        q: str = "",
        site: str = "",
        min_score: str = "",
        score: str = "",
        sort: str = "score",
        page: int = 1,
    ):
        return _render_jobs(request, _filters(view, q, site, min_score, score, sort), page)

    @app.post("/jobs/bulk", response_class=HTMLResponse)
    async def jobs_bulk(request: Request):
        form = await request.form()
        action = form.get("action")
        if action not in jobs.BULK:
            raise HTTPException(400, "Acción inválida")
        f = _filters(form.get("view") or "pending", form.get("q") or "", form.get("site") or "",
                     form.get("min_score") or "", form.get("score") or "", form.get("sort") or "score")
        if form.get("all") == "1":
            ids = jobs.matching_ids(f["view"], f["q"], f["site"], f["min_score_int"], f["score"])
        else:
            raw = form.getlist("ids") + str(form.get("ids_csv") or "").split(",")  # ids_csv: from "Deshacer"
            ids = [int(i) for i in raw if str(i).strip().isdigit()]
        changed = jobs.bulk_update(action, ids)
        page = int(form.get("page") or 1) if str(form.get("page") or "1").isdigit() else 1
        undo = {
            "count": len(changed),
            "done": jobs.BULK_DONE[action],
            "inverse": jobs.BULK[action][2],
            "ids": ",".join(map(str, changed)),
            "undone": form.get("undo") == "1",
        }
        response = _render_jobs(request, f, page, partial=True, undo=undo)
        response.headers["HX-Trigger"] = "counts-changed"
        return response

    @app.get("/jobs/counts", response_class=HTMLResponse)
    def job_counts(request: Request):
        return templates.TemplateResponse(request, "jobs/_counts.html", {"counts": jobs.view_counts()})

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int):
        job = _get_or_404(job_id)
        return templates.TemplateResponse(
            request, "jobs/detail.html",
            {"job": job, "docs": jobs.job_documents(job), "folder": jobs.documents_folder(job), "nav": "jobs"},
        )

    @app.post("/jobs/{job_id}/open-folder", response_class=HTMLResponse)
    def open_folder(job_id: int):
        folder = jobs.documents_folder(_get_or_404(job_id))
        if not folder:
            return HTMLResponse('<small class="field-error">Todavía no hay documentos para esta oferta.</small>')
        jobs.open_in_file_manager(folder)
        return HTMLResponse('<small class="muted">Carpeta abierta.</small>')

    @app.post("/jobs/{job_id}/{action}", response_class=HTMLResponse)
    def job_action(request: Request, job_id: int, action: str, ctx: str = Form("row")):
        if action not in ACTIONS:
            raise HTTPException(404)
        _get_or_404(job_id)
        ACTIONS[action](job_id)
        job = jobs.get_job(job_id)
        name = "jobs/_actions.html" if ctx == "detail" else "jobs/_row.html"
        response = templates.TemplateResponse(request, name, {"job": job, "no_select": ctx == "home"})
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


def _filters(view, q, site, min_score, score, sort) -> dict:
    return {
        "view": view if view in jobs.VIEWS else "pending",
        "q": q.strip(),
        "site": site,
        "min_score": min_score,
        "min_score_int": int(min_score) if str(min_score).isdigit() else None,
        "score": score if score in jobs.SCORE_BANDS else "",
        "sort": sort if sort in jobs.SORTS else "score",
    }


def _render_jobs(request: Request, f: dict, page: int, partial: bool = False, undo: dict | None = None):
    items, total = jobs.list_jobs(f["view"], f["q"], f["site"], f["min_score_int"], f["sort"], page, f["score"])
    pages = max(1, -(-total // jobs.PAGE_SIZE))
    if page > pages:  # e.g. the last page emptied by a bulk discard
        page = pages
        items, total = jobs.list_jobs(f["view"], f["q"], f["site"], f["min_score_int"], f["sort"], page, f["score"])
    ctx = {
        "jobs": items,
        "total": total,
        "page": page,
        "pages": pages,
        "filters": f,
        "views": jobs.VIEWS,
        "sorts": jobs.SORTS,
        "bands": jobs.SCORE_BANDS,
        "counts": jobs.view_counts(),
        "sites": jobs.list_sites(),
        "undo": undo,
        "nav": "jobs",
    }
    # HTMX filter changes and bulk actions only need the results block re-rendered.
    if partial or request.headers.get("HX-Target") == "results":
        return templates.TemplateResponse(request, "jobs/_results.html", ctx)
    return templates.TemplateResponse(request, "jobs/list.html", ctx)


def _greeting() -> str:
    from datetime import datetime

    from applypilot.ui.settings import load_profile

    hour = datetime.now().astimezone().hour  # greeting follows the local clock
    hello = "Buenos días" if 5 <= hour < 13 else "Buenas tardes" if hour < 20 else "Buenas noches"
    personal = load_profile().get("personal") or {}
    name = (personal.get("preferred_name") or (personal.get("full_name") or "").split(" ")[0]).strip()
    return f"{hello}, {name}" if name else hello


def _last_run() -> dict | None:
    """The run in progress or the most recent one (from its log file)."""
    from datetime import datetime, timezone

    from applypilot.ui.runner import runner

    run = runner.current
    if run:
        return {"title": run.title, "status": run.status,
                "when": datetime.fromtimestamp(run.finished_at or run.started_at, timezone.utc).isoformat()}
    logs = sorted(config.LOG_DIR.glob("ui-run-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    first = logs[0].read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    from applypilot.ui.pipeline_routes import STAGES

    keys = first.removeprefix("$ applypilot run ").split(" --", 1)[0].split()
    titles = [s.title for s in STAGES if s.key in keys]
    return {"title": " + ".join(titles) or "Ejecución", "status": "logged",
            "when": datetime.fromtimestamp(logs[0].stat().st_mtime, timezone.utc).isoformat()}


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
