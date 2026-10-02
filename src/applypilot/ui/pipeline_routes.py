"""Pipeline page: launch stages and follow their output live."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from applypilot import config
from applypilot.ui.runner import runner
from applypilot.ui.templating import templates

router = APIRouter(prefix="/pipeline")

LOG_TAIL = 400
VALIDATION_MODES = {
    "normal": "Normal (recomendado)",
    "lenient": "Flexible: menos llamadas a la IA, ideal para el plan gratuito",
    "strict": "Estricta: reintenta ante cualquier problema, más llamadas",
}


@dataclass
class Stage:
    key: str
    title: str
    desc: str
    ai: bool = False


STAGES = [
    Stage("discover", "Buscar ofertas", "Busca en los portales que activaste en Setup > Portales."),
    Stage("enrich", "Traer descripciones", "Abre cada oferta nueva para obtener la descripción completa y el link de postulación."),
    Stage("score", "Puntuar", "La IA compara cada oferta con tu CV y le da un puntaje de 1 a 10.", ai=True),
    Stage("tailor", "Personalizar CV", "Escribe un CV adaptado para cada oferta con puntaje suficiente.", ai=True),
    Stage("cover", "Escribir cartas", "Escribe una carta de presentación para cada oferta con CV personalizado.", ai=True),
    Stage("pdf", "Generar PDFs", "Convierte los CVs y cartas a PDF."),
]
PRESETS = {
    "find": ("Buscar ofertas nuevas", ["discover", "enrich"]),
    "ai": ("Procesar con IA", ["score", "tailor", "cover", "pdf"]),
    "all": ("Todo el pipeline", [s.key for s in STAGES]),
}


def _has_llm() -> bool:
    return any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL"))


def _pending(min_score: int) -> dict[str, int]:
    from applypilot.pipeline import _count_pending

    return {s: _count_pending(s, min_score) for s in ("enrich", "score", "tailor", "cover")}


def _stages_ctx(error: str = "") -> dict:
    min_score = config.DEFAULTS["min_score"]
    warnings = []
    if not config.SEARCH_CONFIG_PATH.exists():
        warnings.append(("Todavía no configuraste tus búsquedas: se usaría el ejemplo de San Francisco.", "/setup/searches"))
    if not config.RESUME_PATH.exists():
        warnings.append(("Falta tu CV en texto: las etapas de IA lo necesitan.", "/setup/resume"))
    if not config.PROFILE_PATH.exists():
        warnings.append(("Falta tu perfil: personalizar CVs y cartas lo necesita.", "/setup/profile"))
    return {
        "stages": STAGES,
        "presets": PRESETS,
        "pending": _pending(min_score),
        "min_score": min_score,
        "has_llm": _has_llm(),
        "validation_modes": VALIDATION_MODES,
        "warnings": warnings,
        "error": error,
    }


def _run_ctx() -> dict:
    run = runner.current
    return {"run": run, "log": list(run.lines)[-LOG_TAIL:] if run else []}


@router.get("", response_class=HTMLResponse)
def pipeline_page(request: Request):
    return templates.TemplateResponse(
        request, "pipeline/page.html", {"nav": "pipeline", **_stages_ctx(), **_run_ctx()}
    )


@router.get("/stages", response_class=HTMLResponse)
def stages_partial(request: Request):
    return templates.TemplateResponse(request, "pipeline/_stages.html", _stages_ctx())


@router.post("/run", response_class=HTMLResponse)
async def start_run(request: Request):
    form = await request.form()
    preset = form.get("preset")
    if preset in PRESETS:
        title, stages = PRESETS[preset]
    else:
        stages = [s.key for s in STAGES if s.key in form.getlist("stages")]
        title = " + ".join(s.title for s in STAGES if s.key in stages)

    has_llm = _has_llm()
    ai_keys = {s.key for s in STAGES if s.ai}
    error = ""
    if not stages:
        error = "Elegí al menos una etapa."
    elif not has_llm and ai_keys & set(stages):
        error = "Las etapas de IA necesitan una clave configurada."
    elif runner.busy:
        error = "Ya hay una ejecución en curso."

    if error:
        return templates.TemplateResponse(request, "pipeline/_stages.html", _stages_ctx(error))

    min_score = _clamp(form.get("min_score"), config.DEFAULTS["min_score"], 1, 10)
    workers = _clamp(form.get("workers"), 1, 1, 8)
    validation = form.get("validation") if form.get("validation") in VALIDATION_MODES else "normal"
    runner.start(title, [
        "run", *stages,
        "--min-score", str(min_score),
        "--workers", str(workers),
        "--validation", validation,
    ])
    # The run panel lives outside the form; refresh it out-of-band.
    response = templates.TemplateResponse(request, "pipeline/_stages.html", _stages_ctx())
    response.headers["HX-Trigger"] = "run-started"
    return response


@router.get("/status", response_class=HTMLResponse)
def run_status(request: Request, was_running: bool = False):
    ctx = _run_ctx()
    response = templates.TemplateResponse(request, "pipeline/_run.html", ctx)
    if was_running and ctx["run"] and not ctx["run"].running:
        response.headers["HX-Trigger"] = "run-finished"  # refresh pending counts
    return response


@router.post("/stop", response_class=HTMLResponse)
def stop_run(request: Request):
    runner.stop()
    return templates.TemplateResponse(request, "pipeline/_run.html", _run_ctx())


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default
