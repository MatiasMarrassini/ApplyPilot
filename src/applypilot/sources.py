"""Registry of every job source, grouped by region, and which ones the user has turned on.

Sources come from four places:
  board:<name>     JobSpy boards (LinkedIn, Indeed, ...)
  native:<name>    built-in extractors in discovery/native.py (no AI)
  site:<name>      direct sites in config/sites.yaml (read with AI, smartextract)
  workday:<key>    employer portals in config/employers.yaml

The user's choices live in searches.yaml under `sources` as {key: true/false};
sources without a choice use their default. The JobSpy board list is also
mirrored to `sites`, the key discovery/jobspy.py reads.
"""

from __future__ import annotations

from dataclasses import dataclass

GROUPS: list[tuple[str, str, str]] = [
    ("intl", "Internacionales", "Portales globales. Buscan en la ubicación que pongas en Búsquedas."),
    ("ar", "Argentina", "Portales argentinos."),
    ("latam", "Latinoamérica", "Ofertas de la región, presenciales y remotas."),
    ("remote", "Remoto global", "Solo trabajo remoto. Muchas ofertas piden residir en EE.UU. o Europa."),
    ("multinational", "Multinacionales", "Portales propios (Workday) de empresas globales. Algunas contratan en Argentina."),
    ("us", "Estados Unidos", "Portales con ofertas casi solo de EE.UU."),
    ("ca", "Canadá", "Portales y empresas canadienses."),
    ("other", "Otros", "Sitios agregados a mano sin grupo."),
]
GROUP_KEYS = {g for g, _, _ in GROUPS}

# Used when the user never chose boards (same default as discovery/jobspy.py).
DEFAULT_BOARDS = ["indeed", "linkedin", "zip_recruiter"]

BOARDS: list[tuple[str, str, str, str]] = [
    # key, name, group, note
    ("linkedin", "LinkedIn", "intl", ""),
    ("indeed", "Indeed", "intl", "El país se elige en Búsquedas (por ejemplo, argentina)."),
    ("google", "Google Jobs", "intl", ""),
    ("glassdoor", "Glassdoor", "intl", "Suele no reconocer ubicaciones fuera de EE.UU."),
    ("zip_recruiter", "ZipRecruiter", "us", "Solo EE.UU. y Canadá: desde otros países responde con error."),
]

NATIVE: list[tuple[str, str, str, str]] = [
    ("getonbrd", "GetOnBoard", "latam", "API oficial. Trae empresa y descripción completa."),
    ("empleosit", "EmpleosIT", "ar", "Portal argentino de tecnología."),
    ("computrabajo", "Computrabajo", "ar", "El portal más grande de Argentina, todos los rubros."),
]


@dataclass
class Source:
    key: str
    name: str
    group: str
    kind: str  # board | native | site | workday
    uses_ai: bool
    note: str = ""
    default: bool = True


def all_sources() -> list[Source]:
    from applypilot.config import load_sites_config
    from applypilot.discovery.workday import load_employers

    out = [Source(f"board:{k}", n, g, "board", False, note) for k, n, g, note in BOARDS]
    # New sources start off so existing setups don't change behaviour until chosen.
    out += [Source(f"native:{k}", n, g, "native", False, note, default=False) for k, n, g, note in NATIVE]
    for site in load_sites_config().get("sites", []) or []:
        group = site.get("group") if site.get("group") in GROUP_KEYS else "other"
        out.append(Source(f"site:{site['name']}", site["name"], group, "site", True))
    for key, emp in (load_employers() or {}).items():
        group = emp.get("group") if emp.get("group") in GROUP_KEYS else "other"
        out.append(Source(f"workday:{key}", emp.get("name", key), group, "workday", False))
    return out


def _board_default(search_cfg: dict, board: str) -> bool:
    boards = search_cfg.get("sites")
    return board in (boards if isinstance(boards, list) else DEFAULT_BOARDS)


def is_enabled(source: Source, search_cfg: dict) -> bool:
    choices = search_cfg.get("sources") or {}
    if source.key in choices:
        return bool(choices[source.key])
    if source.kind == "board":
        return _board_default(search_cfg, source.key.split(":", 1)[1])
    return source.default


def enabled_keys(search_cfg: dict) -> set[str]:
    return {s.key for s in all_sources() if is_enabled(s, search_cfg)}


def apply_choices(search_cfg: dict, enabled: set[str]) -> dict:
    """Record a full on/off choice for every known source (mutates and returns cfg)."""
    search_cfg["sources"] = {s.key: s.key in enabled for s in all_sources()}
    search_cfg["sites"] = [k for k, *_ in BOARDS if f"board:{k}" in enabled]
    return search_cfg


# --- What discovery should run ------------------------------------------------

def enabled_boards(search_cfg: dict) -> list[str]:
    on = enabled_keys(search_cfg)
    return [k for k, *_ in BOARDS if f"board:{k}" in on]


def enabled_native(search_cfg: dict) -> list[str]:
    on = enabled_keys(search_cfg)
    return [k for k, *_ in NATIVE if f"native:{k}" in on]


def enabled_sites(search_cfg: dict) -> list[dict]:
    from applypilot.config import load_sites_config

    on = enabled_keys(search_cfg)
    return [s for s in load_sites_config().get("sites", []) or [] if f"site:{s['name']}" in on]


def enabled_employers(search_cfg: dict) -> dict:
    from applypilot.discovery.workday import load_employers

    on = enabled_keys(search_cfg)
    return {k: v for k, v in (load_employers() or {}).items() if f"workday:{k}" in on}
