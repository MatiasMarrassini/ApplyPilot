"""Built-in extractors for Argentine and Latin American job sources (no AI needed).

  getonbrd      GetOnBoard public API (https://www.getonbrd.com/api/v0)
  empleosit     EmpleosIT search results + detail page (https://www.empleosit.com.ar)
  computrabajo  Computrabajo Argentina search results (https://ar.computrabajo.com);
                its detail pages carry JobPosting JSON-LD, so enrichment reads them without AI

Every source searches each query from searches.yaml, respects `results_per_site`
and `hours_old`, applies the user's location filter, and stores the company.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from applypilot import config
from applypilot.database import init_db
from applypilot.discovery.jobspy import _load_location_config, _location_ok

log = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PAUSE = 1.0  # seconds between requests to the same site
MAX_PAGES = 5


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9"},
                        timeout=30, follow_redirects=True)


def _text(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


# --- GetOnBoard ---------------------------------------------------------------

GOB_API = "https://www.getonbrd.com/api/v0/search/jobs"
GOB_MODALITY = {"remote_local": "remoto", "hybrid": "híbrido"}


def _gob_keep(attrs: dict) -> bool:
    """Argentina, or remote open to any country."""
    countries = attrs.get("countries") or []
    return "Argentina" in countries or "Remote" in countries


def _gob_job(item: dict) -> dict:
    a = item["attributes"]
    company = (((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name")
    sections = [
        (a.get("description_headline") or "Descripción", a.get("description")),
        ("Proyecto", a.get("projects")),
        (a.get("functions_headline") or "Funciones", a.get("functions")),
        (a.get("desirable_headline") or "Deseable", a.get("desirable")),
        (a.get("benefits_headline") or "Beneficios", a.get("benefits")),
    ]
    description = "\n\n".join(f"{title}\n{_text(body)}" for title, body in sections if _text(body))
    countries = [c for c in a.get("countries") or [] if c != "Remote"]
    modality = GOB_MODALITY.get(a.get("remote_modality"), "")
    if "Remote" in (a.get("countries") or []) or not countries:
        location = "Remoto"
    else:
        location = ", ".join(countries) + (f" ({modality})" if modality else "")
    salary = None
    if a.get("min_salary") or a.get("max_salary"):
        salary = "USD " + "-".join(str(v) for v in (a.get("min_salary"), a.get("max_salary")) if v) + "/mes"
    published = a.get("published_at")
    return {
        "url": item["links"]["public_url"],
        "title": a.get("title"),
        "company": company,
        "location": location,
        "salary": salary,
        "description": description[:500],
        "full_description": description,
        "posted_at": datetime.fromtimestamp(published, timezone.utc) if published else None,
    }


def fetch_getonbrd(queries: list[str], limit: int, client: httpx.Client) -> list[dict]:
    jobs: dict[str, dict] = {}
    for query in queries:
        found = 0
        for page in range(1, MAX_PAGES + 1):
            resp = client.get(GOB_API, params={"query": query, "per_page": 50, "page": page,
                                               "expand": '["company"]'})
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                if _gob_keep(item.get("attributes") or {}):
                    job = _gob_job(item)
                    jobs.setdefault(job["url"], job)
                    found += 1
            if found >= limit or page >= (data.get("meta") or {}).get("total_pages", 1):
                break
            time.sleep(PAUSE)
        time.sleep(PAUSE)
    return list(jobs.values())


# --- EmpleosIT ----------------------------------------------------------------

EIT_SEARCH = "https://www.empleosit.com.ar/search-results-jobs/"


def parse_empleosit_list(html: str) -> tuple[list[dict], str | None]:
    """Jobs on a results page, plus the searchId the site uses for paging."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.listing-section"):
        link = card.select_one(".listing-title a[href*='/display-job/']")
        if not link:
            continue
        posted = card.select_one(".posted-ico")
        try:
            posted_at = datetime.strptime(_clean(posted.get_text()), "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except (AttributeError, ValueError):
            posted_at = None
        company = card.select_one(".company-ico")
        brief = card.select_one(".show-brief")
        location = card.select_one(".location-ico")
        jobs.append({
            "url": _strip_query(link["href"]),
            "title": _clean(link.get_text()),
            "company": _clean(company.get_text()) if company else None,
            "location": _clean(location.get_text()) if location else None,
            "description": _clean(brief.get_text()).removeprefix("Descripción del empleo:").strip() if brief else None,
            "posted_at": posted_at,
        })
    search_id = re.search(r"searchId=([\d.]+)", html)
    return jobs, search_id.group(1) if search_id else None


def parse_empleosit_detail(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    blocks = [b.get_text("\n", strip=True) for b in soup.select(".displayFieldBlock")]
    return "\n\n".join(b for b in blocks if b)


def fetch_empleosit(queries: list[str], limit: int, client: httpx.Client) -> list[dict]:
    jobs: dict[str, dict] = {}
    for query in queries:
        params = {"action": "search", "listing_type[equal]": "Job", "keywords[all_words]": query}
        found = 0
        for page in range(1, MAX_PAGES + 1):
            resp = client.get(EIT_SEARCH, params=params)
            resp.raise_for_status()
            page_jobs, search_id = parse_empleosit_list(resp.text)
            for job in page_jobs:
                jobs.setdefault(job["url"], job)
            found += len(page_jobs)
            if not page_jobs or not search_id or found >= limit:
                break
            params = {"searchId": search_id, "action": "search", "page": page + 1, "view": "list"}
            time.sleep(PAUSE)
        time.sleep(PAUSE)
    return list(jobs.values())


def fill_empleosit_details(jobs: list[dict], client: httpx.Client) -> None:
    """The listing only has a snippet and the site's JSON-LD is broken, so read the page."""
    for job in jobs:
        try:
            resp = client.get(job["url"])
            resp.raise_for_status()
            job["full_description"] = parse_empleosit_detail(resp.text) or None
        except httpx.HTTPError as e:
            log.warning("EmpleosIT detail failed for %s: %s", job["url"], e)
        time.sleep(PAUSE)


# --- Computrabajo -------------------------------------------------------------

CT_BASE = "https://ar.computrabajo.com"


def _ct_slug(query: str) -> str:
    plain = unicodedata.normalize("NFKD", query).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def _ct_age(text: str, now: datetime) -> datetime | None:
    """'Hace 15 horas', 'Ayer', 'Hace 3 días', 'Hace 30+ días' -> approximate post time."""
    t = _clean(text).lower()
    if "minuto" in t or "hora" in t:
        n = re.search(r"(\d+)", t)
        hours = int(n.group(1)) if n and "hora" in t else 0
        return now - timedelta(hours=hours)
    if "ayer" in t:
        return now - timedelta(days=1)
    n = re.search(r"(\d+)\+?\s*d[ií]a", t)
    if n:
        return now - timedelta(days=int(n.group(1)))
    return None


def parse_computrabajo_list(html: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("article.box_offer"):
        link = card.select_one("a.js-o-link")
        if not link or not link.get("href"):
            continue
        company = card.select_one("a[offer-grid-article-company-url]")
        location = None
        for p in card.select("p.fs16"):
            if p.select_one("a[offer-grid-article-company-url]"):
                continue
            span = p.select_one("span.mr10") or p
            location = _clean(span.get_text()) or None
            break
        modality_text, salary = "", None
        for tag in card.select("div.fs13 span.dIB"):
            text = _clean(tag.get_text())
            if tag.select_one(".i_home_office, .i_home"):  # "Presencial y remoto" / "Remoto"
                modality_text = text
            elif text.startswith("$") or tag.select_one(".i_salary"):
                salary = text
        if modality_text == "Remoto":
            location = "Remoto"
        elif modality_text and location:
            location = f"{location} ({modality_text})"
        age = card.select_one("p.fc_aux")
        jobs.append({
            "url": urljoin(CT_BASE, link["href"].split("#", 1)[0]),
            "title": _clean(link.get_text()),
            "company": _clean(company.get_text()) if company else None,
            "location": location,
            "salary": salary,
            "description": None,
            "posted_at": _ct_age(age.get_text(), now) if age else None,
        })
    return jobs


def fetch_computrabajo(queries: list[str], limit: int, client: httpx.Client) -> list[dict]:
    jobs: dict[str, dict] = {}
    for query in queries:
        slug = _ct_slug(query)
        if not slug:
            continue
        found = 0
        for page in range(1, MAX_PAGES + 1):
            resp = client.get(f"{CT_BASE}/trabajo-de-{slug}", params={"p": page} if page > 1 else None)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            page_jobs = parse_computrabajo_list(resp.text)
            new = [j for j in page_jobs if j["url"] not in jobs]
            for job in new:
                jobs[job["url"]] = job
            found += len(new)
            if not new or found >= limit:
                break
            time.sleep(PAUSE)
        time.sleep(PAUSE)
    return list(jobs.values())


# --- Storage ------------------------------------------------------------------

SITE_NAMES = {"getonbrd": "GetOnBoard", "empleosit": "EmpleosIT", "computrabajo": "Computrabajo"}


def store(conn: sqlite3.Connection, jobs: list[dict], source: str, accept: list[str], reject: list[str],
          hours_old: int | None) -> dict:
    """Insert new jobs (skipping old or wrong-location ones); fill in the company on known ones."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_old) if hours_old else None
    stats = {"new": 0, "existing": 0, "too_old": 0, "wrong_location": 0}
    for job in jobs:
        posted = job.get("posted_at")
        if cutoff and posted and posted < cutoff:
            stats["too_old"] += 1
            continue
        if not _location_ok(job.get("location"), accept, reject):
            stats["wrong_location"] += 1
            continue
        full = job.get("full_description")
        try:
            conn.execute(
                "INSERT INTO jobs (url, title, company, salary, description, location, site, strategy, "
                "discovered_at, full_description, application_url, detail_scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job["url"], job.get("title"), job.get("company"), job.get("salary"), job.get("description"),
                 job.get("location"), SITE_NAMES[source], f"native_{source}", now.isoformat(),
                 full, job["url"], now.isoformat() if full else None),
            )
            stats["new"] += 1
        except sqlite3.IntegrityError:
            stats["existing"] += 1
            if job.get("company"):
                conn.execute("UPDATE jobs SET company = ? WHERE url = ? AND company IS NULL", (job["company"], job["url"]))
    conn.commit()
    return stats


def run_native_discovery(sources: list[str], search_cfg: dict | None = None) -> dict:
    """Run the enabled native sources; one failing source doesn't stop the others."""
    search_cfg = search_cfg if search_cfg is not None else config.load_search_config()
    queries = [q["query"] for q in search_cfg.get("queries", []) if q.get("query")]
    if not queries or not sources:
        return {}
    defaults = search_cfg.get("defaults") or {}
    limit = int(defaults.get("results_per_site", 50))
    hours_old = defaults.get("hours_old", 72)
    accept, reject = _load_location_config(search_cfg)
    conn = init_db()

    results: dict = {}
    with _client() as client:
        for source in sources:
            try:
                if source == "getonbrd":
                    jobs = fetch_getonbrd(queries, limit, client)
                elif source == "empleosit":
                    jobs = fetch_empleosit(queries, limit, client)
                    known = {r[0] for r in conn.execute("SELECT url FROM jobs WHERE site = 'EmpleosIT'")}
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old or 10**6)
                    fill_empleosit_details([j for j in jobs if j["url"] not in known
                                            and (not j.get("posted_at") or j["posted_at"] >= cutoff)
                                            and _location_ok(j.get("location"), accept, reject)], client)
                elif source == "computrabajo":
                    jobs = fetch_computrabajo(queries, limit, client)
                else:
                    log.warning("Unknown native source: %s", source)
                    continue
                stats = store(conn, jobs, source, accept, reject, hours_old)
                log.info("%s: %d found, %d new, %d already known, %d too old, %d other location",
                         SITE_NAMES[source], len(jobs), stats["new"], stats["existing"],
                         stats["too_old"], stats["wrong_location"])
                results[source] = stats
            except Exception as e:  # noqa: BLE001 - one broken site must not stop the others
                log.error("%s failed: %s", SITE_NAMES.get(source, source), e)
                results[source] = {"error": str(e)}
    return results
