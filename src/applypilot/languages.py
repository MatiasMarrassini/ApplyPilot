"""Language handling for generated documents (tailored resume, cover letter).

Documents are written in the job posting's language unless the profile pins
one (`preferences.document_language`: auto | es | en). The resume text uses
per-language section titles; the PDF builder and validator map them back to
the canonical English keys.
"""

from __future__ import annotations

import re

SUPPORTED = ("en", "es")
LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}

# Canonical section key -> title written in the resume text.
SECTION_TITLES: dict[str, dict[str, str]] = {
    "en": {"SUMMARY": "SUMMARY", "TECHNICAL SKILLS": "TECHNICAL SKILLS", "EXPERIENCE": "EXPERIENCE",
           "PROJECTS": "PROJECTS", "EDUCATION": "EDUCATION"},
    "es": {"SUMMARY": "PERFIL PROFESIONAL", "TECHNICAL SKILLS": "HABILIDADES TÉCNICAS", "EXPERIENCE": "EXPERIENCIA",
           "PROJECTS": "PROYECTOS", "EDUCATION": "EDUCACIÓN"},
}
# Section headings shown in the PDF.
PDF_LABELS: dict[str, dict[str, str]] = {
    "en": {"SUMMARY": "Summary", "TECHNICAL SKILLS": "Technical Skills", "EXPERIENCE": "Experience",
           "PROJECTS": "Projects", "EDUCATION": "Education"},
    "es": {"SUMMARY": "Perfil profesional", "TECHNICAL SKILLS": "Habilidades técnicas", "EXPERIENCE": "Experiencia",
           "PROJECTS": "Proyectos", "EDUCATION": "Educación"},
}
# Any written title -> canonical key (both languages).
CANONICAL_SECTIONS: dict[str, str] = {
    title: key for titles in SECTION_TITLES.values() for key, title in titles.items()
}

SKILL_CATEGORIES: dict[str, list[str]] = {
    "en": ["Languages", "Frameworks", "DevOps & Infra", "Databases", "Tools"],
    "es": ["Lenguajes", "Frameworks", "DevOps e infraestructura", "Bases de datos", "Herramientas"],
}

LETTER_GREETING = {"en": "Dear Hiring Manager,", "es": "Estimado equipo de selección:"}
# Accepted openings when validating / stripping model preambles.
LETTER_OPENINGS = ("dear", "estimad", "hola")

_ES_WORDS = {"de", "la", "el", "que", "y", "en", "los", "las", "para", "con", "una", "por", "del", "se", "como",
             "experiencia", "conocimientos", "requisitos", "buscamos", "trabajo", "equipo", "años", "empresa",
             "beneficios", "nuestro", "nuestra", "desarrollo", "sobre", "también", "más"}
_EN_WORDS = {"the", "and", "of", "to", "with", "for", "you", "we", "our", "is", "are", "will", "your", "in",
             "experience", "requirements", "team", "years", "work", "about", "benefits", "role", "skills"}


def detect_language(text: str | None) -> str:
    """'es' or 'en' from common words; English when unsure."""
    words = re.findall(r"[a-záéíóúñü]+", (text or "")[:4000].lower())
    es = sum(w in _ES_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return "es" if es > en else "en"


def document_language(job: dict, profile: dict | None) -> str:
    """Language to write this job's resume and cover letter in."""
    pref = ((profile or {}).get("preferences") or {}).get("document_language", "auto")
    if pref in SUPPORTED:
        return pref
    return detect_language(f"{job.get('title') or ''}\n{job.get('full_description') or job.get('description') or ''}")
