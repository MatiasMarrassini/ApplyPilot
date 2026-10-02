from applypilot.languages import detect_language, document_language
from applypilot.scoring import scorer
from applypilot.scoring.cover_letter import _build_cover_letter_prompt, _strip_preamble
from applypilot.scoring.pdf import build_html, parse_resume
from applypilot.scoring.tailor import _build_judge_prompt, _build_tailor_prompt, assemble_resume_text
from applypilot.scoring.validator import validate_cover_letter, validate_tailored_resume

ES = ("Buscamos un desarrollador backend con experiencia en Python para sumarse a nuestro equipo. "
      "Requisitos: conocimientos de Django y bases de datos. Ofrecemos beneficios y trabajo remoto.")
EN = "We are looking for a backend engineer with experience in Python to join our team. You will build APIs."
PROFILE = {"personal": {"full_name": "Ana Pérez", "email": "ana@example.com", "city": "Florida Oeste",
                        "province_state": "Buenos Aires", "country": "Argentina"},
           "work_authorization": {"require_sponsorship": "Yes", "work_permit_type": "Ciudadana argentina"}}
DATA = {"title": "Desarrolladora Backend", "summary": "Desarrolladora Python.",
        "skills": {"Lenguajes": "Python", "Herramientas": "Git"},
        "experience": [{"header": "Dev en Acme", "subtitle": "Python | 2023", "bullets": ["Construí APIs"]}],
        "projects": [{"header": "Bot", "bullets": ["Automaticé tareas"]}], "education": "UBA | Licenciatura"}


def test_detect_language():
    assert detect_language(ES) == "es"
    assert detect_language(EN) == "en"
    assert detect_language("") == "en"


def test_document_language_follows_job_unless_pinned():
    assert document_language({"title": "Dev", "full_description": ES}, {}) == "es"
    assert document_language({"title": "Dev", "full_description": EN}, None) == "en"
    assert document_language({"full_description": ES}, {"preferences": {"document_language": "en"}}) == "en"


def test_spanish_resume_round_trips_through_pdf_and_validator():
    text = assemble_resume_text(DATA, PROFILE, "es")
    assert "PERFIL PROFESIONAL" in text and "EXPERIENCIA" in text and "SUMMARY" not in text
    parsed = parse_resume(text)
    assert parsed["lang"] == "es" and {"SUMMARY", "EXPERIENCE", "EDUCATION"} <= parsed["sections"].keys()
    html = build_html(parsed)
    assert "Perfil profesional" in html and "Experiencia" in html and ">Summary<" not in html
    assert not [e for e in validate_tailored_resume(text, PROFILE)["errors"] if "Missing required section" in e]
    english = parse_resume(assemble_resume_text(DATA, PROFILE, "en"))
    assert english["lang"] == "en" and "Summary" in build_html(english)


def test_prompts_carry_the_language():
    assert "LANGUAGE: Spanish" in _build_tailor_prompt(PROFILE, "es") and '"Lenguajes"' in _build_tailor_prompt(PROFILE, "es")
    assert "Translate" in _build_judge_prompt(PROFILE)
    letter_prompt = _build_cover_letter_prompt(PROFILE, "es")
    assert "Estimado equipo de selección:" in letter_prompt and "Spanish" in letter_prompt


def test_spanish_letter_passes_validation():
    letter = "Aquí tenés la carta:\nEstimado equipo de selección:\nConstruí APIs en Python.\nAna"
    cleaned = _strip_preamble(letter)
    assert cleaned.startswith("Estimado")
    assert validate_cover_letter(cleaned, mode="lenient")["passed"]
    assert not validate_cover_letter("Hi there, I built APIs.", mode="lenient")["passed"]


def test_scoring_prompt_knows_where_the_candidate_lives(monkeypatch):
    sent = []

    class Client:
        def chat(self, messages, **kw):
            sent.append(messages)
            return "SCORE: 3\nKEYWORDS: python\nREASONING: Solo para residentes en EE.UU."

    monkeypatch.setattr(scorer, "get_client", lambda: Client())
    result = scorer.score_job("cv", {"title": "Dev", "site": "linkedin", "full_description": EN}, PROFILE)
    system, user = sent[0][0]["content"], sent[0][1]["content"]
    assert "Lives in Florida Oeste, Buenos Aires, Argentina." in user
    assert "Needs visa sponsorship to work abroad: Yes." in user
    assert "score at most 3" in system and "in Spanish" in system
    assert result == {"score": 3, "keywords": "python", "reasoning": "Solo para residentes en EE.UU."}
    scorer.score_job("cv", {"title": "Dev", "site": "x"}, None)
    assert "do not apply location penalties" in sent[1][1]["content"]


def test_real_skills_are_not_flagged_as_fabricated():
    from applypilot.scoring.validator import validate_json_fields

    # "django" is on the generic watchlist; it must not count as invented for a Django developer.
    data = {**DATA, "skills": {"Frameworks": "Django, FastAPI"}}
    django_dev = {**PROFILE, "skills_boundary": {"frameworks": ["Django", "FastAPI"]}}
    assert validate_json_fields(data, django_dev)["passed"]
    errors = validate_json_fields(data, {**PROFILE, "skills_boundary": {"frameworks": ["FastAPI"]}})["errors"]
    assert errors == ["Fabricated skill: 'django'"]


def test_comma_joined_companies_is_what_breaks_validation():
    from applypilot.scoring.validator import validate_json_fields

    data = {**DATA, "experience": [{"header": "Dev en Accusys Technology", "bullets": ["x"]},
                                   {"header": "Dev en Autocosmos", "bullets": ["y"]}]}
    joined = {**PROFILE, "resume_facts": {"preserved_companies": ["Accusys Technology, Autocosmos"]}}
    split = {**PROFILE, "resume_facts": {"preserved_companies": ["Accusys Technology", "Autocosmos"]}}
    assert not validate_json_fields(data, joined)["passed"]
    assert validate_json_fields(data, split)["passed"]
