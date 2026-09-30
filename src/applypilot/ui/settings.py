"""Read/write the user's config files (profile, resume, searches, .env) for the setup UI.

Every writer starts from the existing file and only replaces the keys the
form manages, so hand-edited or unknown keys survive a save.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

import yaml

from applypilot import config

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


EEO_DEFAULT = "Decline to self-identify"
OTHER = "__other__"


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text | email | url | password | yesno | lines | number | choice
    required: bool = False
    hint: str = ""
    placeholder: str = ""
    # kind="choice": (stored value, label). Stored values use the standard
    # wording of US application forms so the auto-apply agent can match them.
    options: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Section:
    key: str
    title: str
    description: str
    fields: list[Field] = field(default_factory=list)


PROFILE_SECTIONS: list[Section] = [
    Section("personal", "Datos personales", "Se usan para completar formularios de postulación.", [
        Field("full_name", "Nombre completo (legal)", required=True),
        Field("preferred_name", "Nombre preferido", hint="Si lo dejás vacío se usa tu primer nombre."),
        Field("email", "Email", "email", required=True),
        Field("phone", "Teléfono"),
        Field("address", "Dirección"),
        Field("city", "Ciudad", required=True),
        Field("province_state", "Provincia / Estado"),
        Field("country", "País", required=True),
        Field("postal_code", "Código postal"),
        Field("linkedin_url", "LinkedIn", "url", placeholder="https://www.linkedin.com/in/..."),
        Field("github_url", "GitHub", "url"),
        Field("portfolio_url", "Portfolio", "url"),
        Field("website_url", "Sitio web", "url"),
        Field("password", "Contraseña para portales de empleo", "password",
              hint="La usa el auto-apply cuando un sitio pide crear cuenta. Se guarda en texto plano en "
                   "profile.json: usá una contraseña exclusiva para esto."),
    ]),
    Section("work_authorization", "Autorización de trabajo", "", [
        Field("legally_authorized_to_work", "¿Estás autorizado/a a trabajar en el país objetivo?", "yesno"),
        Field("require_sponsorship", "¿Necesitás sponsorship de visa?", "yesno"),
        Field("work_permit_type", "Tipo de permiso", placeholder="Ciudadano/a, residente, work permit…"),
    ]),
    Section("availability", "Disponibilidad", "", [
        Field("earliest_start_date", "Fecha de inicio más temprana", placeholder="Immediately"),
        Field("available_for_full_time", "Disponible full-time", "yesno"),
        Field("available_for_contract", "Disponible para contrato", "yesno"),
    ]),
    Section("compensation", "Remuneración", "Lo que responde el auto-apply cuando un formulario pregunta salario.", [
        Field("salary_expectation", "Expectativa salarial (anual)", "number"),
        Field("salary_currency", "Moneda", placeholder="USD"),
        Field("salary_range_min", "Rango mínimo", "number"),
        Field("salary_range_max", "Rango máximo", "number"),
        Field("currency_conversion_note", "Nota de conversión", placeholder="Opcional"),
    ]),
    Section("experience", "Experiencia", "", [
        Field("years_of_experience_total", "Años de experiencia", "number"),
        Field("education_level", "Nivel educativo", placeholder="Bachelor's Degree"),
        Field("current_job_title", "Puesto actual"),
        Field("current_company", "Empresa actual"),
        Field("target_role", "Rol buscado", placeholder="Backend Engineer"),
    ]),
    Section("resume_facts", "Datos que la IA nunca debe cambiar",
            "Al personalizar tu CV, la IA reorganiza pero conserva exactamente estos datos. Uno por línea.", [
        Field("preserved_companies", "Empresas", "lines"),
        Field("preserved_projects", "Proyectos", "lines"),
        Field("preserved_school", "Institución educativa"),
        Field("real_metrics", "Métricas reales", "lines", placeholder="Reduje la latencia un 40%"),
    ]),
    Section("eeo_voluntary", "Datos demográficos voluntarios (EEO)",
            "Preguntas opcionales de formularios en EE.UU. Podés dejar las respuestas por defecto.", [
        Field("gender", "Género", "choice", options=[
            ("Male", "Masculino"),
            ("Female", "Femenino"),
            ("Non-binary", "No binario"),
            (EEO_DEFAULT, "Prefiero no responder"),
        ]),
        Field("race_ethnicity", "Etnia", "choice", options=[
            ("Hispanic or Latino", "Hispano / Latino"),
            ("White", "Blanco"),
            ("Black or African American", "Negro / Afroamericano"),
            ("Asian", "Asiático"),
            ("American Indian or Alaska Native", "Indígena americano / Nativo de Alaska"),
            ("Native Hawaiian or Other Pacific Islander", "Nativo de Hawái / Islas del Pacífico"),
            ("Two or More Races", "Dos o más"),
            (EEO_DEFAULT, "Prefiero no responder"),
        ]),
        Field("veteran_status", "¿Sos veterano/a de las fuerzas armadas de EE.UU.?", "choice", options=[
            ("I am not a protected veteran", "No"),
            ("I identify as one or more of the classifications of protected veteran", "Sí"),
            (EEO_DEFAULT, "Prefiero no responder"),
        ]),
        Field("disability_status", "¿Tenés alguna discapacidad?", "choice", options=[
            ("No, I do not have a disability", "No"),
            ("Yes, I have a disability (or previously had a disability)", "Sí"),
            (EEO_DEFAULT, "Prefiero no responder"),
        ]),
    ]),
]

DEFAULT_SKILL_CATEGORIES = ["languages", "frameworks", "devops", "databases", "tools"]
SKILL_EXAMPLES = {
    "languages": "Python, JavaScript, SQL",
    "programming_languages": "Python, JavaScript, SQL",
    "frameworks": "Django, React, FastAPI",
    "devops": "Docker, AWS, CI/CD",
    "databases": "PostgreSQL, MongoDB, Redis",
    "tools": "Git, Jira, Linux",
}
# Short answers people type by hand, mapped to the standard option.
_CHOICE_ALIASES = {
    "veteran_status": {"no": 0, "yes": 1, "si": 1, "sí": 1},
    "disability_status": {"no": 0, "yes": 1, "si": 1, "sí": 1},
    "gender": {"m": 0, "masculino": 0, "hombre": 0, "f": 1, "femenino": 1, "mujer": 1},
    "race_ethnicity": {"latino": 0, "latina": 0, "hispanic": 0, "hispano": 0},
}


def load_profile() -> dict:
    if not config.PROFILE_PATH.exists():
        return {}
    return json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))


def _yes_no(value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value or ""


def profile_form_values(profile: dict) -> dict[str, str]:
    """Flatten the profile into ``section.key`` -> display string."""
    values: dict[str, str] = {}
    for section in PROFILE_SECTIONS:
        data = profile.get(section.key, {}) or {}
        for f in section.fields:
            v = data.get(f.key, "")
            if f.kind == "lines":
                v = "\n".join(v) if isinstance(v, list) else (v or "")
            elif f.kind == "yesno":
                v = _yes_no(v)
            elif f.kind == "password":
                v = ""  # never echo secrets back to the browser
            elif f.kind == "choice":
                v = normalize_choice(f, v) or (EEO_DEFAULT if section.key == "eeo_voluntary" else "")
            elif section.key == "eeo_voluntary" and not v:
                v = EEO_DEFAULT
            values[f"{section.key}.{f.key}"] = "" if v is None else str(v)
    return values


def normalize_choice(f: Field, value) -> str:
    """Map a stored answer onto one of the field's option values when it matches one."""
    if not value:
        return ""
    text = str(value).strip()
    for opt, _ in f.options:
        if opt.lower() == text.lower():
            return opt
    alias = _CHOICE_ALIASES.get(f.key, {}).get(text.lower())
    return f.options[alias][0] if alias is not None else text


def skill_rows(profile: dict) -> list[tuple[str, str, str]]:
    """(category, comma-separated skills, example placeholder) rows for the form."""
    boundary = profile.get("skills_boundary") or {}
    rows = [(k, ", ".join(v) if isinstance(v, list) else str(v)) for k, v in boundary.items()]
    if not rows:
        rows = [(c, "") for c in DEFAULT_SKILL_CATEGORIES]
    rows.append(("", ""))  # one blank row to add a category
    return [(cat, vals, "Ej.: " + SKILL_EXAMPLES.get(cat, "habilidades separadas por comas")) for cat, vals in rows]


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split_commas(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


def save_profile(form: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Validate and merge form data into profile.json. Returns (profile, errors)."""
    profile = load_profile()
    errors: dict[str, str] = {}

    for section in PROFILE_SECTIONS:
        data = dict(profile.get(section.key) or {})
        for f in section.fields:
            name = f"{section.key}.{f.key}"
            raw = (form.get(name) or "").strip()
            if f.required and not raw:
                errors[name] = "Obligatorio"
            if f.kind == "email" and raw and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
                errors[name] = "Email inválido"
            if f.kind == "url" and raw and not raw.startswith(("http://", "https://")):
                errors[name] = "Debe empezar con https://"
            if f.kind == "password":
                if raw:
                    data[f.key] = raw
                else:
                    data.setdefault(f.key, "")  # empty input keeps the saved password
            elif f.kind == "lines":
                data[f.key] = _split_lines(raw)
            elif f.kind == "choice":
                if raw == OTHER:
                    raw = (form.get(f"{name}.other") or "").strip()
                    if not raw:
                        errors[name] = "Escribí tu respuesta"
                data[f.key] = raw
            else:
                data[f.key] = raw
        profile[section.key] = data

    skills: dict[str, list[str]] = {}
    i = 0
    while f"skills.cat.{i}" in form:
        cat = re.sub(r"\s+", "_", (form.get(f"skills.cat.{i}") or "").strip().lower())
        vals = _split_commas(form.get(f"skills.vals.{i}") or "")
        if cat and vals:
            skills[cat] = vals
        i += 1
    profile["skills_boundary"] = skills

    if not errors:
        config.PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile, errors


def profile_complete(profile: dict) -> bool:
    personal = profile.get("personal") or {}
    return all(personal.get(k) for k in ("full_name", "email", "city", "country"))


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def load_resume() -> str:
    return config.RESUME_PATH.read_text(encoding="utf-8") if config.RESUME_PATH.exists() else ""


def save_resume(text: str) -> None:
    config.RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.RESUME_PATH.write_text(text.replace("\r\n", "\n").strip() + "\n", encoding="utf-8")


def save_resume_pdf(data: bytes) -> None:
    config.RESUME_PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.RESUME_PDF_PATH.write_bytes(data)


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------

BOARDS = [
    ("indeed", "Indeed"),
    ("linkedin", "LinkedIn"),
    ("glassdoor", "Glassdoor"),
    ("zip_recruiter", "ZipRecruiter"),
    ("google", "Google Jobs"),
]
# Discovery's default when `sites` is missing (discovery/jobspy.py::_full_crawl)
DEFAULT_BOARDS = ["indeed", "linkedin", "zip_recruiter"]
LOCATION_ROWS_MIN = 3


def load_searches() -> tuple[dict, bool]:
    """Return (user search config, whether searches.yaml exists)."""
    if not config.SEARCH_CONFIG_PATH.exists():
        return {}, False
    return yaml.safe_load(config.SEARCH_CONFIG_PATH.read_text(encoding="utf-8")) or {}, True


def searches_form_values(cfg: dict) -> dict:
    queries = cfg.get("queries") or []
    tiers = {t: "\n".join(q["query"] for q in queries if q.get("tier", 1) == t and q.get("query")) for t in (1, 2, 3)}
    locations = [(loc.get("location", ""), bool(loc.get("remote"))) for loc in cfg.get("locations") or []]
    locations += [("", False)] * max(1, LOCATION_ROWS_MIN - len(locations))
    defaults = cfg.get("defaults") or {}
    return {
        "tiers": tiers,
        "locations": locations,
        # Older configs keep the list under location.accept_patterns
        "accept": "\n".join(cfg.get("location_accept") or (cfg.get("location") or {}).get("accept_patterns") or []),
        "reject": "\n".join(cfg.get("location_reject_non_remote") or []),
        "sites": cfg.get("sites") or DEFAULT_BOARDS,
        "results_per_site": defaults.get("results_per_site", 50),
        "hours_old": defaults.get("hours_old", 72),
        "country_indeed": defaults.get("country_indeed", ""),
    }


def _int(value: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def save_searches(form) -> tuple[dict, dict[str, str]]:
    """Merge the search form into searches.yaml. ``form`` is a starlette FormData."""
    cfg, _ = load_searches()
    errors: dict[str, str] = {}

    queries = [{"query": q, "tier": t} for t in (1, 2, 3) for q in _split_lines(form.get(f"tier{t}") or "")]
    if not queries:
        errors["tier1"] = "Agregá al menos un puesto a buscar"

    locations = []
    i = 0
    while f"loc.{i}" in form:
        name = (form.get(f"loc.{i}") or "").strip()
        if name:
            locations.append({"location": name, "remote": form.get(f"loc_remote.{i}") == "on"})
        i += 1
    if not locations:
        errors["locations"] = "Agregá al menos una ubicación"

    sites = [s for s, _ in BOARDS if s in form.getlist("sites")]
    if not sites:
        errors["sites"] = "Elegí al menos un portal"

    accept = _split_lines(form.get("accept") or "")
    cfg["queries"] = queries
    cfg["locations"] = locations
    cfg["sites"] = sites
    # Discovery reads location_accept / location_reject_non_remote; the apply
    # prompt reads location.accept_patterns. Keep both in sync.
    cfg["location_accept"] = accept
    cfg["location_reject_non_remote"] = _split_lines(form.get("reject") or "")
    if not isinstance(cfg.get("location"), dict):
        cfg["location"] = {}
    cfg["location"]["accept_patterns"] = accept

    defaults = dict(cfg.get("defaults") or {})
    defaults["results_per_site"] = _int(form.get("results_per_site"), 50, 1, 500)
    defaults["hours_old"] = _int(form.get("hours_old"), 72, 1, 24 * 60)
    country = (form.get("country_indeed") or "").strip().lower()
    if country:
        defaults["country_indeed"] = country
    else:
        defaults.pop("country_indeed", None)
    cfg["defaults"] = defaults
    cfg.pop("boards", None)  # never read by discovery; `sites` is the real key

    if not errors:
        config.SEARCH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = "# ApplyPilot search configuration (edited from the web UI)\n"
        config.SEARCH_CONFIG_PATH.write_text(
            header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    return cfg, errors


# ---------------------------------------------------------------------------
# .env (API keys)
# ---------------------------------------------------------------------------

PROVIDERS = {
    "gemini": ("Google Gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
    "openai": ("OpenAI", "OPENAI_API_KEY", "gpt-4o-mini"),
    "local": ("Modelo local (Ollama, llama.cpp)", None, "local-model"),
}
SECRET_KEYS = {"GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY", "CAPSOLVER_API_KEY"}
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def read_env() -> dict[str, str]:
    """Parse ~/.applypilot/.env (only the file, not the process environment)."""
    from dotenv import dotenv_values

    if not config.ENV_PATH.exists():
        return {}
    return {k: v for k, v in dotenv_values(config.ENV_PATH).items() if v}


def _quote(value: str) -> str:
    if re.search(r"[\s#\"'\\]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def update_env(updates: dict[str, str | None]) -> None:
    """Set (str) or remove (None) keys in .env, keeping every other line intact.

    Also applies the change to os.environ so the running server sees it
    (load_dotenv never overrides variables that are already set).
    """
    lines = config.ENV_PATH.read_text(encoding="utf-8").splitlines() if config.ENV_PATH.exists() else [
        "# ApplyPilot configuration"
    ]
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and m.group(1) in pending:
            value = pending.pop(m.group(1))
            if value is not None:
                out.append(f"{m.group(1)}={_quote(value)}")
            continue
        out.append(line)
    out += [f"{k}={_quote(v)}" for k, v in pending.items() if v is not None]

    config.ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def mask(value: str | None) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def keys_form_values(env: dict[str, str]) -> dict:
    # Same precedence as llm._detect_provider: LLM_URL, then Gemini, then OpenAI.
    if env.get("LLM_URL"):
        provider = "local"
    elif env.get("OPENAI_API_KEY") and not env.get("GEMINI_API_KEY"):
        provider = "openai"
    else:
        provider = "gemini"
    return {
        "provider": provider,
        "masked": {k: mask(env.get(k)) for k in SECRET_KEYS},
        "LLM_MODEL": env.get("LLM_MODEL", ""),
        "LLM_URL": env.get("LLM_URL", ""),
        "PROXY": env.get("PROXY", ""),
        "CHROME_PATH": env.get("CHROME_PATH", ""),
    }


def save_keys(form) -> dict[str, str]:
    """Apply the API-keys form to .env. Returns errors (empty on success)."""
    env = read_env()
    errors: dict[str, str] = {}
    provider = form.get("provider") or "gemini"
    if provider not in PROVIDERS:
        errors["provider"] = "Proveedor inválido"
        return errors

    updates: dict[str, str | None] = {}

    def secret(name: str) -> str | None:
        """New value if typed, the saved one if left blank, None if cleared."""
        if form.get(f"clear_{name}") == "on":
            return None
        typed = (form.get(name) or "").strip()
        return typed or env.get(name)

    if provider == "local":
        url = (form.get("LLM_URL") or "").strip()
        if not url.startswith(("http://", "https://")):
            errors["LLM_URL"] = "Ingresá la URL del servidor, por ejemplo http://localhost:11434/v1"
        updates["LLM_URL"] = url
        updates["LLM_API_KEY"] = secret("LLM_API_KEY")
    else:
        key_name = PROVIDERS[provider][1]
        value = secret(key_name)
        if not value:
            errors[key_name] = "Falta la API key"
        updates[key_name] = value
        updates["LLM_URL"] = None  # a local URL would take precedence over the key
        if provider == "openai":
            updates["GEMINI_API_KEY"] = None  # Gemini takes precedence over OpenAI

    model = (form.get("LLM_MODEL") or "").strip()
    if re.search(r"\s", model):
        errors["LLM_MODEL"] = ("Usá el identificador del modelo, sin espacios (por ejemplo gemini-2.5-flash), "
                               "no el nombre comercial. \"Probar conexión\" te muestra los disponibles.")
    updates["LLM_MODEL"] = model or None
    updates["CAPSOLVER_API_KEY"] = secret("CAPSOLVER_API_KEY")
    updates["PROXY"] = (form.get("PROXY") or "").strip() or None
    updates["CHROME_PATH"] = (form.get("CHROME_PATH") or "").strip() or None

    if not errors:
        update_env(updates)
    return errors


def _llm_env_from_form(form) -> dict[str, str]:
    """Config values for a connection test: typed values win, blanks fall back to .env."""
    saved = read_env()
    provider = form.get("provider") or "gemini"

    def pick(name: str) -> str:
        return (form.get(name) or "").strip() or saved.get(name, "")

    env = {"LLM_MODEL": (form.get("LLM_MODEL") or "").strip()}
    if provider == "local":
        env["LLM_URL"] = (form.get("LLM_URL") or "").strip()
        env["LLM_API_KEY"] = pick("LLM_API_KEY")
    elif provider in PROVIDERS:
        key_name = PROVIDERS[provider][1]
        env[key_name] = pick(key_name)
    return env


def test_llm(form) -> dict:
    """Send one tiny request with the form's settings. Never raises."""
    from applypilot.llm import LLMClient, resolve_provider

    env = _llm_env_from_form(form)
    try:
        base_url, model, api_key = resolve_provider(env)
    except RuntimeError:
        return {"ok": False, "error": "Falta la API key (o la URL del servidor local)."}

    client = LLMClient(base_url, model, api_key, max_retries=1, timeout=30)
    try:
        start = time.monotonic()
        reply = client.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=256)
        return {"ok": True, "model": model, "seconds": time.monotonic() - start, "reply": (reply or "").strip()[:80]}
    except Exception as e:  # noqa: BLE001 - any failure is shown to the user
        result = {"ok": False, "model": model, "error": str(e) or type(e).__name__, "models": []}
        # Overloaded / rate-limited: the key and model are valid, the provider is just busy.
        # The pipeline retries these with backoff, so don't report a config error.
        result["busy"] = result["error"].startswith(("HTTP 429", "HTTP 503"))
        if result["busy"]:
            return result
        try:
            models = client.list_models()
            if "generativelanguage" in base_url:
                models = [m for m in models if "gemini" in m]
            result["models"] = models[:40]
        except Exception:  # the model list is only a hint
            logging.getLogger(__name__).debug("Could not list models", exc_info=True)
        return result
    finally:
        client.close()
