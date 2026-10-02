"""Setup pages: overview, profile, resume, searches and API keys."""

from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse

from applypilot import config
from applypilot.checks import run_checks
from applypilot.ui import settings
from applypilot.ui.templating import templates

router = APIRouter(prefix="/setup")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Where in the UI each doctor check can be fixed
CHECK_LINKS = {
    "profile.json": "/setup/profile",
    "resume.txt": "/setup/resume",
    "searches.yaml": "/setup/searches",
    "LLM API key": "/setup/keys",
    "CapSolver API key": "/setup/keys",
}


def _render(request: Request, name: str, section: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"nav": "setup", "section": section, **ctx})


def _form_or_page(request: Request, partial: str, page: str, section: str, **ctx) -> HTMLResponse:
    # HTMX form posts only need the form re-rendered.
    name = partial if request.headers.get("HX-Request") == "true" else page
    return _render(request, name, section, **ctx)


# --- Overview --------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def overview(request: Request):
    from applypilot.config import TIER_LABELS, get_tier

    profile = settings.load_profile()
    _, has_searches = settings.load_searches()
    env = settings.read_env()
    steps = [
        ("Perfil", "/setup/profile", settings.profile_complete(profile),
         "Tus datos personales, experiencia y habilidades."),
        ("CV", "/setup/resume", config.RESUME_PATH.exists(),
         "Tu CV base en texto, el que la IA usa para puntuar y personalizar."),
        ("Búsquedas", "/setup/searches", has_searches,
         "Qué puestos buscar y dónde."),
        ("Portales", "/setup/portals", has_searches and bool(settings.load_searches()[0].get("sources")),
         "En qué sitios buscar, por país."),
        ("Claves de IA", "/setup/keys", any(env.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL")),
         "El modelo de IA que puntúa ofertas y escribe CVs y cartas."),
    ]
    tier = get_tier()
    return _render(
        request, "setup/overview.html", "overview",
        steps=steps, checks=run_checks(), check_links=CHECK_LINKS,
        tier=tier, tier_label=TIER_LABELS[tier], app_dir=config.APP_DIR,
    )


# --- Profile ---------------------------------------------------------------

def _profile_ctx(profile: dict, values: dict | None = None, **extra) -> dict:
    return {
        "sections": settings.PROFILE_SECTIONS,
        "values": values if values is not None else settings.profile_form_values(profile),
        "skills": settings.skill_rows(profile),
        "has_password": bool((profile.get("personal") or {}).get("password")),
        "is_new": not config.PROFILE_PATH.exists(),
        "errors": {},
        "saved": False,
        **extra,
    }


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return _render(request, "setup/profile.html", "profile", **_profile_ctx(settings.load_profile()))


@router.post("/profile", response_class=HTMLResponse)
async def profile_save(request: Request):
    form = await request.form()
    profile, errors = settings.save_profile(form)
    # On error, re-show what the user typed instead of the saved values.
    values = {k: str(v) for k, v in form.items() if k != "personal.password"} if errors else None
    ctx = _profile_ctx(profile, values, errors=errors, saved=not errors)
    return _form_or_page(request, "setup/_profile_form.html", "setup/profile.html", "profile", **ctx)


# --- Resume ----------------------------------------------------------------

def _resume_ctx(**extra) -> dict:
    return {
        "resume": settings.load_resume(),
        "has_pdf": config.RESUME_PDF_PATH.exists(),
        "errors": {},
        "upload_msg": "",
        "text_msg": "",
        "oob": False,
        **extra,
    }


@router.get("/resume", response_class=HTMLResponse)
def resume_page(request: Request):
    return _render(request, "setup/resume.html", "resume", **_resume_ctx())


@router.post("/resume", response_class=HTMLResponse)
async def resume_save(request: Request):
    form = await request.form()
    text = str(form.get("resume") or "")
    if not text.strip():
        ctx = _resume_ctx(resume=text, errors={"resume": "El CV no puede quedar vacío"})
    else:
        settings.save_resume(text)
        ctx = _resume_ctx(text_msg="CV guardado")
    return _form_or_page(request, "setup/_resume_text.html", "setup/resume.html", "resume", **ctx)


@router.post("/resume/upload", response_class=HTMLResponse)
async def resume_upload(request: Request, file: UploadFile):
    """Re-renders only the upload form, so unsaved text in the textarea survives.

    A .txt upload replaces the text on purpose; that box is swapped out-of-band.
    """
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    name = (file.filename or "").lower()
    replace_text = False
    if len(data) > MAX_UPLOAD_BYTES:
        ctx = _resume_ctx(errors={"file": "El archivo supera 5 MB"})
    elif name.endswith(".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        settings.save_resume(text)
        replace_text = True
        ctx = _resume_ctx(upload_msg=f"Se cargó y guardó el texto de {file.filename}.", oob=True)
    elif name.endswith(".pdf"):
        settings.save_resume_pdf(data)
        ctx = _resume_ctx(upload_msg=(
            f"Se guardó {file.filename} como tu CV en PDF. La IA trabaja con texto: "
            "si todavía no lo hiciste, copiá el contenido del PDF, pegalo abajo y guardalo."
        ))
    else:
        ctx = _resume_ctx(errors={"file": "Subí un archivo .txt o .pdf"})

    upload = templates.get_template("setup/_resume_upload.html").render(ctx)
    if replace_text:
        upload += templates.get_template("setup/_resume_text.html").render(ctx)
    return HTMLResponse(upload)


# --- Searches --------------------------------------------------------------

def _searches_ctx(cfg: dict, exists: bool, **extra) -> dict:
    return {
        "v": settings.searches_form_values(cfg),
        "exists": exists,
        "errors": {},
        "saved": False,
        **extra,
    }


@router.get("/searches", response_class=HTMLResponse)
def searches_page(request: Request):
    cfg, exists = settings.load_searches()
    return _render(request, "setup/searches.html", "searches", **_searches_ctx(cfg, exists))


@router.post("/searches", response_class=HTMLResponse)
async def searches_save(request: Request):
    form = await request.form()
    cfg, errors = settings.save_searches(form)
    ctx = _searches_ctx(cfg, exists=config.SEARCH_CONFIG_PATH.exists(), errors=errors, saved=not errors)
    return _form_or_page(request, "setup/_searches_form.html", "setup/searches.html", "searches", **ctx)


# --- API keys --------------------------------------------------------------

def _keys_ctx(**extra) -> dict:
    return {
        "v": settings.keys_form_values(settings.read_env()),
        "providers": settings.PROVIDERS,
        "errors": {},
        "saved": False,
        **extra,
    }


@router.get("/keys", response_class=HTMLResponse)
def keys_page(request: Request):
    return _render(request, "setup/keys.html", "keys", **_keys_ctx())


@router.post("/keys", response_class=HTMLResponse)
async def keys_save(request: Request):
    form = await request.form()
    errors = settings.save_keys(form)
    ctx = _keys_ctx(errors=errors, saved=not errors)
    if errors:
        # Keep the provider the user picked so the right fields stay visible.
        ctx["v"]["provider"] = form.get("provider") or ctx["v"]["provider"]
    return _form_or_page(request, "setup/_keys_form.html", "setup/keys.html", "keys", **ctx)


@router.post("/keys/test", response_class=HTMLResponse)
async def keys_test(request: Request):
    form = await request.form()
    return templates.TemplateResponse(request, "setup/_llm_test.html", {"result": settings.test_llm(form)})


# --- Portals ---------------------------------------------------------------

def _portals_ctx(cfg: dict, exists: bool, **extra) -> dict:
    return {
        "groups": settings.portals_view(cfg),
        "exists": exists,
        "country_indeed": (cfg.get("defaults") or {}).get("country_indeed", ""),
        "errors": {},
        "saved": False,
        **extra,
    }


@router.get("/portals", response_class=HTMLResponse)
def portals_page(request: Request):
    cfg, exists = settings.load_searches()
    return _render(request, "setup/portals.html", "portals", **_portals_ctx(cfg, exists))


@router.post("/portals", response_class=HTMLResponse)
async def portals_save(request: Request):
    form = await request.form()
    cfg, errors = settings.save_portals(form)
    if errors:
        # Show what the user ticked, not the saved state.
        from applypilot import sources
        cfg = {**cfg, "sources": {s.key: s.key in form.getlist("src") for s in sources.all_sources()}}
    ctx = _portals_ctx(cfg, config.SEARCH_CONFIG_PATH.exists(), errors=errors, saved=not errors)
    return _form_or_page(request, "setup/_portals_form.html", "setup/portals.html", "portals", **ctx)
