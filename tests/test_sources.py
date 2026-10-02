from datetime import datetime, timedelta, timezone

import pytest
import yaml

from applypilot import config, sources
from applypilot.database import get_connection, init_db
from applypilot.discovery import native

# --- registry -----------------------------------------------------------------

def test_defaults_keep_previous_behaviour():
    on = sources.enabled_keys({})
    assert {"board:indeed", "board:linkedin", "board:zip_recruiter"} <= on
    assert "board:google" not in on and "native:computrabajo" not in on  # new sources start off
    assert "site:Eluta" in on and "workday:td" in on  # everything else ran before, and still does
    # a legacy `sites` list still decides the JobSpy boards
    assert sources.enabled_boards({"sites": ["linkedin"]}) == ["linkedin"]


def test_choices_override_defaults_and_mirror_boards():
    cfg = sources.apply_choices({}, {"board:linkedin", "native:computrabajo", "site:RemoteOK", "workday:salesforce"})
    assert cfg["sites"] == ["linkedin"]  # what discovery/jobspy.py reads
    assert sources.enabled_native(cfg) == ["computrabajo"]
    assert [s["name"] for s in sources.enabled_sites(cfg)] == ["RemoteOK"]
    assert list(sources.enabled_employers(cfg)) == ["salesforce"]


def test_every_source_has_a_known_group():
    groups = {g for g, _, _ in sources.GROUPS}
    srcs = sources.all_sources()
    assert all(s.group in groups for s in srcs)
    assert {s.group for s in srcs if s.key.startswith("site:Eluta") or s.key == "workday:td"} == {"ca"}


# --- Setup > Portales -----------------------------------------------------------

@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from applypilot.ui.server import create_app

    config.SEARCH_CONFIG_PATH.unlink(missing_ok=True)
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_portals_page_groups_and_save(client):
    HX = {"HX-Request": "true"}
    page = client.get("/setup/portals").text
    for title in ("Argentina", "Latinoamérica", "Canadá", "Multinacionales", "Computrabajo", "GetOnBoard", "EmpleosIT"):
        assert title in page
    assert "Primero configurá tus búsquedas" in page
    r = client.post("/setup/portals", data={"src": ["board:linkedin"]}, headers=HX)
    assert "Configurá primero tus búsquedas" in r.text and not config.SEARCH_CONFIG_PATH.exists()

    config.SEARCH_CONFIG_PATH.write_text(yaml.safe_dump({"queries": [{"query": "python", "tier": 1}]}), encoding="utf-8")
    r = client.post("/setup/portals", data={"src": []}, headers=HX)
    assert "Activá al menos un portal" in r.text

    r = client.post("/setup/portals", data={"src": ["board:linkedin", "native:getonbrd", "native:computrabajo"]}, headers=HX)
    assert "Guardado" in r.text
    cfg = yaml.safe_load(config.SEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["queries"] == [{"query": "python", "tier": 1}]  # search settings untouched
    assert cfg["sites"] == ["linkedin"]
    assert cfg["sources"]["native:getonbrd"] is True and cfg["sources"]["site:Eluta"] is False
    assert sources.enabled_native(cfg) == ["getonbrd", "computrabajo"]


# --- built-in extractors (parsing only, no network) --------------------------------

EIT_LIST = """
<div class="listing-section"><div class="listing-right">
  <div class="listing-title"><a href="https://www.empleosit.com.ar/display-job/95863/Python-Developer-Ssr.html?searchId=1790899474.6406&amp;page=1">Python Developer Ssr</a></div>
  <div class="show-brief"><strong>Descripción del empleo:</strong> Responsabilidades: diseñar APIs</div>
  <div class="listing-info"><span class="captions-field location-ico">Ciudad Autónoma de Buenos Aires (CABA)</span>
    <span class="captions-field posted-ico">30/09/2026</span>
    <span class="captions-field company-ico"><a href="#">Werben HR</a></span></div>
</div></div>
<a href="?searchId=1790899474.6406&amp;action=search&amp;page=2">2</a>
"""

CT_LIST = """
<article class="box_offer">
  <h2><a class="js-o-link fc_base" href="/ofertas-de-trabajo/oferta-de-desarrollador-python-ABC#lc=x">Desarrollador Python</a></h2>
  <p class="fs16"><a offer-grid-article-company-url href="#">Provincia NET</a></p>
  <p class="fs16"><span class="mr10">San Nicolás, Capital Federal</span></p>
  <div class="fs13"><span class="dIB"><span class="icon i_salary"></span>$ 1.000.000,00 (Mensual)</span>
    <span class="dIB"><span class="icon i_home_office"></span>Presencial y remoto</span></div>
  <p class="fc_aux">Hace  15  horas</p>
</article>
<article class="box_offer">
  <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-de-senior-python-DEF">Senior Python Engineer</a></h2>
  <p class="fs16"><span class="mr10">Retiro, Capital Federal</span></p>
  <div class="fs13"><span class="dIB"><span class="icon i_home"></span>Remoto</span></div>
  <p class="fc_aux">Hace 5 días</p>
</article>
"""


def test_parse_empleosit():
    jobs, search_id = native.parse_empleosit_list(EIT_LIST)
    assert search_id == "1790899474.6406"
    assert jobs == [{
        "url": "https://www.empleosit.com.ar/display-job/95863/Python-Developer-Ssr.html",
        "title": "Python Developer Ssr", "company": "Werben HR",
        "location": "Ciudad Autónoma de Buenos Aires (CABA)",
        "description": "Responsabilidades: diseñar APIs",
        "posted_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
    }]


def test_parse_computrabajo():
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    first, second = native.parse_computrabajo_list(CT_LIST, now)
    assert first["url"] == "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-desarrollador-python-ABC"
    assert first["company"] == "Provincia NET" and first["salary"] == "$ 1.000.000,00 (Mensual)"
    assert first["location"] == "San Nicolás, Capital Federal (Presencial y remoto)"
    assert first["posted_at"] == now - timedelta(hours=15)
    assert second["company"] is None and second["location"] == "Remoto"
    assert second["posted_at"] == now - timedelta(days=5)
    assert native._ct_slug("Diseñador UX/UI Sr.") == "disenador-ux-ui-sr"


def test_getonbrd_job_and_country_filter():
    item = {
        "links": {"public_url": "https://www.getonbrd.com/jobs/backend-acme"},
        "attributes": {
            "title": "Backend Dev", "countries": ["Argentina"], "remote_modality": "hybrid",
            "description": "<p>Python y <strong>Django</strong></p>", "functions": "<ul><li>APIs</li></ul>",
            "min_salary": 2000, "max_salary": 3000, "published_at": 1790895876,
            "company": {"data": {"attributes": {"name": "Acme"}}},
        },
    }
    job = native._gob_job(item)
    assert job["company"] == "Acme" and job["location"] == "Argentina (híbrido)"
    assert job["salary"] == "USD 2000-3000/mes"
    assert "Python y\nDjango" in job["full_description"] and "APIs" in job["full_description"]
    assert native._gob_keep({"countries": ["Argentina"]}) and native._gob_keep({"countries": ["Remote"]})
    assert not native._gob_keep({"countries": ["Chile"]})


def test_store_filters_age_location_and_backfills_company():
    conn = init_db()
    conn.execute("DELETE FROM jobs")
    conn.execute("INSERT INTO jobs (url, title, site) VALUES ('https://ct/known', 'Old', 'Computrabajo')")
    conn.commit()
    now = datetime.now(timezone.utc)
    jobs = [
        {"url": "https://ct/new", "title": "Dev", "company": "Acme", "location": "Remoto", "posted_at": now},
        {"url": "https://ct/old", "title": "Old", "location": "Remoto", "posted_at": now - timedelta(days=10)},
        {"url": "https://ct/far", "title": "Far", "location": "Mendoza", "posted_at": now},
        {"url": "https://ct/known", "title": "Old", "company": "Globant", "location": "Remoto", "posted_at": now},
    ]
    stats = native.store(conn, jobs, "computrabajo", accept=["Buenos Aires"], reject=[], hours_old=72)
    assert stats == {"new": 1, "existing": 1, "too_old": 1, "wrong_location": 1}
    rows = dict(get_connection().execute("SELECT url, company FROM jobs"))
    assert rows == {"https://ct/new": "Acme", "https://ct/known": "Globant"}
    site = get_connection().execute("SELECT site FROM jobs WHERE url = 'https://ct/new'").fetchone()[0]
    assert site == "Computrabajo"
