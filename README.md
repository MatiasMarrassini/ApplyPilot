# ApplyPilot — Web UI fork

**A local web interface for [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot), the open-source job application pipeline, plus job sources for Argentina and Latin America and a set of bug fixes.**

Set up your profile and searches from a form, run the pipeline and watch its log live, then review every job with its score, tailored resume and cover letter, all from your browser.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](LICENSE)

> **Credit:** ApplyPilot was created by [Pickle-Pixel](https://github.com/Pickle-Pixel/ApplyPilot). This fork builds on their work and keeps its license (AGPL-3.0). It is not published to PyPI: `pip install applypilot` installs the original project, without the web UI. Install this fork [from source](#quick-start).

<!-- TODO: add screenshots of Inicio, Ofertas and Pipeline (e.g. docs/screenshots/*.png) -->

---

## What this fork adds

- **Local web UI** (`applypilot ui`): setup forms, a pipeline runner with live logs, a job list with filters and bulk actions, and a detail view for each job. The interface is in Spanish.
- **Sources for Argentina and Latin America**: Computrabajo, EmpleosIT and GetOnBoard, with sources grouped by country so you only search where you want to work.
- **Documents in the job's language**: resumes and cover letters are written in Spanish or English, matching the posting.
- **Location-aware scoring**: jobs you can't take because of where they're based (e.g. "US only") get a low score instead of a high one.
- **Bug fixes**: the hiring company is used instead of the job board's name, failed AI calls are no longer saved as a score of 0, documents for jobs with the same title no longer overwrite each other, and more.

Full list in the [CHANGELOG](CHANGELOG.md).

---

## Quick start

Requires Python 3.11+ and Git. The web UI lives on the `feature/web-ui` branch.

Windows (PowerShell):

```powershell
git clone -b feature/web-ui https://github.com/MatiasMarrassini/ApplyPilot.git
cd ApplyPilot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[ui]"
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
playwright install chromium
applypilot ui
```

macOS / Linux: same commands, but activate the environment with `source .venv/bin/activate`.

`applypilot ui` opens `http://127.0.0.1:8765` in your browser; keep the terminal open while you use it. Next time, only `cd ApplyPilot`, activate the environment and run `applypilot ui`. Options: `--port 9000`, `--no-browser`.

> **Why is `python-jobspy` installed separately?** It pins an exact numpy version that conflicts with pip's resolver, but works fine with modern numpy. `--no-deps` skips the resolver and the next line installs what it really needs. pip may also warn that jobspy wants `pandas<3` or an older `regex`; you can ignore it.

> **PowerShell won't run `Activate.ps1`** ("running scripts is disabled"): run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and call `.venv\Scripts\applypilot ui` directly.

> **Moved the project folder?** `pip install -e` remembers where the code is. After moving or renaming the folder, run `pip install -e ".[ui]"` again from the new location, or `applypilot` will fail with `No module named 'applypilot'`.

You'll need an AI key for scoring, tailoring and cover letters. A free [Gemini](https://aistudio.google.com) key is enough; OpenAI and local models (Ollama, llama.cpp) also work.

---

## First run

1. **Setup**: fill in your profile, paste your resume as plain text, define your searches, and add an AI key. Use **Probar conexión** to check the key and model before saving. The model field needs the technical ID (e.g. `gemini-2.5-flash`), not the marketing name; a failed test lists the models your key can use.
2. **Portales** (in Setup): choose which job sources to search, grouped by country or region (international boards, Argentina, Latin America, remote, multinationals, US, Canada). Tick a whole country or single portals. Sources marked "Usa IA" read each page with the AI model and spend tokens on every search.
3. **Pipeline**: run **Buscar ofertas nuevas** (discover + enrich), then **Procesar con IA** (score, tailor, cover letters, PDFs).
4. **Ofertas**: filter by status, score band (7+, 5–6, 4 or less, unscored) and board. Open a job to read why it got its score, its tailored resume and cover letter, then mark it as applied or discard it. **Abrir carpeta** opens the job's folder in `applications/`.
5. **Bulk actions**: tick rows (or the header box for the whole page, then **Seleccionar las N que coinciden** for every page) to discard or mark many jobs at once. Each bulk action can be undone right after.

**Inicio** (home) shows how your search is going, from jobs found to applications sent, the best-scored jobs waiting for review, and the last pipeline run.

### Good to know

- The server only listens on `127.0.0.1` and rejects requests from other sites. API keys are never sent back to the browser in full.
- One pipeline run at a time. Each run is the regular `applypilot run ...` command in the background, with its full output saved to `~/.applypilot/logs/ui-run-*.log`. **Detener** stops it; closing the terminal stops it too. Work finished before stopping is kept.
- Discarded jobs are skipped by every stage and stay in the database, so later searches recognize them and don't add them again. Discarding is not deleting.
- The UI and the CLI share the same files and database, so you can mix them.
- Auto-apply is not in the UI; use `applypilot apply` from the terminal (see [Auto-apply](#auto-apply)).

### Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `No module named 'applypilot'` | The project folder was moved or renamed. Run `pip install -e ".[ui]"` again from the new folder. |
| Scoring stops with `HTTP 400: ... unexpected model name format` | Wrong model name in **Claves de IA**. Use the technical ID; **Probar conexión** lists valid ones. |
| `HTTP 503` / `HTTP 429` from the AI provider | Provider busy or free-tier limit reached. The pipeline retries with backoff; try later or pick another model. |
| `ZipRecruiter response status code 403` in the log | ZipRecruiter only serves the US and Canada. Untick it in **Búsquedas**. |
| `Glassdoor: location not parsed` | Glassdoor doesn't recognize that location. The other boards still run. |
| Only remote jobs show up | `location_accept` is empty: add your cities in **Búsquedas → Filtro de ubicación**. |

---

## How the pipeline works

ApplyPilot runs six independent stages. Run them all or pick the ones you need.

| Stage | What happens |
|-------|-------------|
| **1. Discover** | Searches Indeed, LinkedIn, Glassdoor, ZipRecruiter and Google Jobs (via JobSpy), 48 Workday employer portals, 30 direct career sites, and Computrabajo, EmpleosIT and GetOnBoard. Only the sources you enable are used. Deduplicates by URL. |
| **2. Enrich** | Visits each job and extracts the full description: structured data (JSON-LD) first, then CSS selectors, then AI extraction for unknown layouts. |
| **3. Score** | AI rates every job 1–10 against your profile (9–10 strong match, 7–8 good, 5–6 moderate, 1–4 skip). Only jobs above your threshold move on. |
| **4. Tailor** | AI rewrites your resume for each job: reorders experience, highlights relevant skills, adds keywords. Your `resume_facts` (companies, projects, metrics) are kept exactly; it never makes things up. |
| **5. Cover letter** | AI writes a cover letter for each job, tied to the company and role. |
| **6. Auto-apply** | Claude Code drives Chrome to fill and submit application forms. Terminal only. |

### Configuration

Generated by the web UI's **Setup** page or `applypilot init`, and stored in `~/.applypilot/` (override with the `APPLYPILOT_DIR` environment variable):

| File | Contents |
|------|----------|
| `profile.json` | Contact info, work authorization, compensation, experience, skills, resume facts and EEO defaults. Used for scoring, tailoring and form filling. |
| `searches.yaml` | Search queries and locations. Discovery reads `queries` (`query` + `tier`), `locations` (`location` + `remote`), `sites`, `location_accept` / `location_reject_non_remote`, `defaults` (`results_per_site`, `hours_old`, `country_indeed`) and `sources` (enabled portals). With an empty `location_accept`, only remote jobs are kept. |
| `.env` | API keys and runtime settings: `GEMINI_API_KEY`, `LLM_MODEL`, `CAPSOLVER_API_KEY` (optional). |
| `applications/` | One folder per job: `resume.txt`/`.pdf`, `cover_letter.txt`/`.pdf`, a copy of the posting (`job.txt`) and the tailoring report. |

Shipped with the package, in `src/applypilot/config/`: `employers.yaml` (Workday portals), `sites.yaml` (direct career sites, blocked sites, manual ATS domains) and `searches.example.yaml`.

### Auto-apply

Auto-apply needs Node.js 18+ (for `npx`), Chrome or Chromium, and the [Claude Code CLI](https://claude.ai/code). Claude Code opens Chrome, goes to each application page, fills in your details, uploads the tailored resume and cover letter, answers screening questions and submits. The Playwright MCP server is set up automatically for each worker.

An optional [CapSolver](https://www.capsolver.com) key solves CAPTCHAs (hCaptcha, reCAPTCHA, Turnstile, FunCaptcha). Without it, applications blocked by a CAPTCHA are marked as failed.

Start with `applypilot apply --dry-run` to fill forms without submitting.

---

## CLI reference

```
applypilot ui                           # Local web UI (this fork)
applypilot init                         # First-time setup wizard
applypilot doctor                       # Check setup, show what's missing
applypilot run [stages...]              # Run pipeline stages (or 'all')
applypilot run --workers 4              # Parallel discovery/enrichment
applypilot run --stream                 # Run stages concurrently
applypilot run --min-score 8            # Override score threshold
applypilot run --dry-run                # Preview without executing
applypilot run --validation lenient     # Relax validation (recommended for Gemini free tier)
applypilot run --validation strict      # Strictest validation (retries on any banned word)
applypilot apply                        # Launch auto-apply
applypilot apply --workers 3            # Parallel browser workers
applypilot apply --dry-run              # Fill forms without submitting
applypilot apply --continuous           # Run forever, polling for new jobs
applypilot apply --headless             # Headless browser mode
applypilot apply --url URL              # Apply to a specific job
applypilot apply --mark-applied URL     # Mark a job as applied
applypilot apply --mark-failed URL      # Mark a job as failed
applypilot apply --reset-failed         # Reset failed jobs for retry
applypilot apply --gen --url URL        # Write the prompt file for manual debugging
applypilot status                       # Pipeline statistics
applypilot dashboard                    # Open the HTML results dashboard
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and coding standards. Tests: `pytest tests/`.

## License

[GNU Affero General Public License v3.0](LICENSE), same as the original project. You are free to use, modify and distribute this software. If you deploy a modified version as a service, you must release its source code under the same license.
