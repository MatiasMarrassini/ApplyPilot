import json

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from applypilot import config
from applypilot.ui.server import create_app

HX = {"HX-Request": "true"}
ENV_KEYS = ["GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL", "LLM_MODEL", "LLM_API_KEY",
            "CAPSOLVER_API_KEY", "PROXY", "CHROME_PATH"]

PROFILE_FORM = {
    "personal.full_name": "Ada Lovelace",
    "personal.email": "ada@example.com",
    "personal.city": "Buenos Aires",
    "personal.country": "Argentina",
    "personal.password": "s3cret",
    "work_authorization.legally_authorized_to_work": "Yes",
    "resume_facts.preserved_companies": "Acme\nGlobex\n",
    "skills.cat.0": "Languages",
    "skills.vals.0": "Python, SQL",
    "skills.cat.1": "",
    "skills.vals.1": "",
}


@pytest.fixture
def client(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for path in (config.PROFILE_PATH, config.RESUME_PATH, config.RESUME_PDF_PATH,
                 config.SEARCH_CONFIG_PATH, config.ENV_PATH):
        path.unlink(missing_ok=True)
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_setup_pages_render(client):
    for path in ("/setup", "/setup/profile", "/setup/resume", "/setup/searches", "/setup/portals", "/setup/keys"):
        assert client.get(path).status_code == 200, path


def test_profile_validation_and_save(client):
    r = client.post("/setup/profile", data={**PROFILE_FORM, "personal.email": "nope"}, headers=HX)
    assert "Email inválido" in r.text
    assert not config.PROFILE_PATH.exists()

    r = client.post("/setup/profile", data=PROFILE_FORM, headers=HX)
    assert "Guardado" in r.text
    assert "s3cret" not in r.text  # never echoed back
    profile = json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile["personal"]["full_name"] == "Ada Lovelace"
    assert profile["resume_facts"]["preserved_companies"] == ["Acme", "Globex"]
    assert profile["skills_boundary"] == {"languages": ["Python", "SQL"]}

    # Blank password field keeps the saved one; unknown keys survive.
    profile["custom"] = {"keep": True}
    config.PROFILE_PATH.write_text(json.dumps(profile), encoding="utf-8")
    client.post("/setup/profile", data={**PROFILE_FORM, "personal.password": ""}, headers=HX)
    profile = json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile["personal"]["password"] == "s3cret"
    assert profile["custom"] == {"keep": True}


def test_resume_text_and_upload(client):
    client.post("/setup/resume", data={"resume": "My CV\r\nline 2"}, headers=HX)
    assert config.RESUME_PATH.read_text(encoding="utf-8") == "My CV\nline 2\n"

    r = client.post("/setup/resume/upload", files={"file": ("cv.txt", b"Uploaded CV")}, headers=HX)
    assert "Uploaded CV" in r.text
    r = client.post("/setup/resume/upload", files={"file": ("cv.docx", b"x")}, headers=HX)
    assert ".txt o .pdf" in r.text


def test_searches_write_the_keys_discovery_reads(client):
    form = {
        "tier1": "Backend Engineer\n", "tier2": "Python Developer", "tier3": "",
        "loc.0": "Buenos Aires, Argentina", "loc.1": "Remote", "loc_remote.1": "on", "loc.2": "",
        "accept": "Buenos Aires\nCABA", "reject": "",
        "results_per_site": "30", "hours_old": "48",
        "country_indeed": "Argentina",
    }
    r = client.post("/setup/searches", data=form, headers=HX)
    assert "Guardado" in r.text
    cfg = yaml.safe_load(config.SEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["queries"] == [{"query": "Backend Engineer", "tier": 1}, {"query": "Python Developer", "tier": 2}]
    assert cfg["locations"] == [{"location": "Buenos Aires, Argentina", "remote": False},
                                {"location": "Remote", "remote": True}]
    assert cfg["location_accept"] == cfg["location"]["accept_patterns"] == ["Buenos Aires", "CABA"]
    assert cfg["defaults"] == {"results_per_site": 30, "hours_old": 48, "country_indeed": "argentina"}

    r = client.post("/setup/searches", data={**form, "tier1": "", "tier2": ""}, headers=HX)
    assert "Agregá al menos un puesto" in r.text


def test_keys_mask_keep_and_switch_provider(client):
    import os

    config.ENV_PATH.write_text("# mine\nSOMETHING_ELSE=1\n", encoding="utf-8")
    r = client.post("/setup/keys", data={"provider": "gemini", "GEMINI_API_KEY": "AIzaSECRET1234"}, headers=HX)
    assert "Guardado" in r.text
    assert "AIzaSECRET1234" not in r.text and "••••1234" in r.text
    assert os.environ["GEMINI_API_KEY"] == "AIzaSECRET1234"

    # Blank key keeps the saved one
    client.post("/setup/keys", data={"provider": "gemini", "GEMINI_API_KEY": ""}, headers=HX)
    env_text = config.ENV_PATH.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIzaSECRET1234" in env_text and "SOMETHING_ELSE=1" in env_text

    # Switching to OpenAI must drop Gemini, which would otherwise take precedence
    client.post("/setup/keys", data={"provider": "openai", "OPENAI_API_KEY": "sk-abc12345678"}, headers=HX)
    env_text = config.ENV_PATH.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" not in env_text and "OPENAI_API_KEY=sk-abc12345678" in env_text
    assert "GEMINI_API_KEY" not in os.environ

    r = client.post("/setup/keys", data={"provider": "local", "LLM_URL": "localhost"}, headers=HX)
    assert "Ingresá la URL" in r.text


def test_pdf_upload_leaves_unsaved_text_alone(client):
    r = client.post("/setup/resume/upload", files={"file": ("cv.pdf", b"%PDF-1.4")}, headers=HX)
    assert config.RESUME_PDF_PATH.read_bytes() == b"%PDF-1.4"
    assert 'id="resume-upload"' in r.text
    assert "<textarea" not in r.text  # the text box isn't re-rendered, so typed text survives

    r = client.post("/setup/resume/upload", files={"file": ("cv.txt", b"From file")}, headers=HX)
    assert 'hx-swap-oob="true"' in r.text and "From file" in r.text


def test_eeo_choices_normalize_and_accept_other(client):
    config.PROFILE_PATH.write_text(json.dumps({"eeo_voluntary": {
        "gender": "male", "race_ethnicity": "Latino", "veteran_status": "No", "disability_status": "Martian",
    }}), encoding="utf-8")
    page = client.get("/setup/profile").text
    assert '<option value="Male" selected>' in page
    assert '<option value="Hispanic or Latino" selected>' in page
    assert '<option value="I am not a protected veteran" selected>' in page
    assert 'value="Martian"' in page  # unknown answer shown as "Otro"

    form = {**PROFILE_FORM, "eeo_voluntary.gender": "__other__", "eeo_voluntary.gender.other": "Agender",
            "eeo_voluntary.disability_status": "No, I do not have a disability"}
    client.post("/setup/profile", data=form, headers=HX)
    eeo = json.loads(config.PROFILE_PATH.read_text(encoding="utf-8"))["eeo_voluntary"]
    assert eeo["gender"] == "Agender"
    assert eeo["disability_status"] == "No, I do not have a disability"

    r = client.post("/setup/profile", data={**form, "eeo_voluntary.gender.other": ""}, headers=HX)
    assert "Escribí tu respuesta" in r.text


def test_skill_placeholders_differ_by_category(client):
    page = client.get("/setup/profile").text
    assert "Ej.: Docker, AWS, CI/CD" in page and "Ej.: PostgreSQL, MongoDB, Redis" in page


def test_connection_test_button(client, monkeypatch):
    from applypilot import llm
    from applypilot.llm import LLMError

    monkeypatch.setattr(llm.LLMClient, "chat", lambda self, *a, **k: (_ for _ in ()).throw(
        LLMError("HTTP 400: Model not found")))
    monkeypatch.setattr(llm.LLMClient, "list_models", lambda self: ["gemini-2.5-flash", "embedding-001"])
    r = client.post("/setup/keys/test", data={"provider": "gemini", "GEMINI_API_KEY": "k",
                                              "LLM_MODEL": "Gemini 3.1 Flash Lite"}, headers=HX)
    assert "No funcionó" in r.text and "Model not found" in r.text
    assert 'data-model="gemini-2.5-flash"' in r.text and "embedding-001" not in r.text

    monkeypatch.setattr(llm.LLMClient, "chat", lambda self, *a, **k: "OK")
    r = client.post("/setup/keys/test", data={"provider": "gemini", "GEMINI_API_KEY": "k"}, headers=HX)
    assert "Funciona" in r.text and "gemini-2.0-flash" in r.text

    r = client.post("/setup/keys/test", data={"provider": "gemini"}, headers=HX)
    assert "Falta la API key" in r.text


def test_model_display_name_is_rejected(client):
    r = client.post("/setup/keys", data={"provider": "gemini", "GEMINI_API_KEY": "k",
                                         "LLM_MODEL": "Gemini 3.1 Flash Lite"}, headers=HX)
    assert "sin espacios" in r.text
    assert not config.ENV_PATH.exists() or "LLM_MODEL" not in config.ENV_PATH.read_text(encoding="utf-8")


def test_connection_test_reports_busy_provider_as_valid_config(client, monkeypatch):
    from applypilot import llm
    from applypilot.llm import LLMError

    monkeypatch.setattr(llm.LLMClient, "chat", lambda self, *a, **k: (_ for _ in ()).throw(
        LLMError("HTTP 503: This model is currently experiencing high demand.")))
    r = client.post("/setup/keys/test", data={"provider": "gemini", "GEMINI_API_KEY": "k",
                                              "LLM_MODEL": "gemini-3.1-flash-lite"}, headers=HX)
    assert "son válidos" in r.text and "No funcionó" not in r.text
