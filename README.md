<!-- logo here -->

> **⚠️ ApplyPilot** is the original open-source project, created by [Pickle-Pixel](https://github.com/Pickle-Pixel) and first published on GitHub on **February 17, 2026**. We are **not affiliated** with applypilot.app, useapplypilot.com, or any other product using the "ApplyPilot" name. These sites are **not associated with this project** and may misrepresent what they offer. If you're looking for the autonomous, open-source job application agent — you're in the right place.

# ApplyPilot

**Applied to 1,000 jobs in 2 days. Fully autonomous. Open source.**

> **This fork adds a local web UI** (setup forms, pipeline runner with live logs, job review) on top of the original CLI, plus a set of bug fixes. It is not published to PyPI: [install it from source](#web-ui-local). Everything below that doesn't mention the UI describes the original project and still applies.

[![PyPI version](https://img.shields.io/pypi/v/applypilot?color=blue)](https://pypi.org/project/applypilot/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Pickle-Pixel/ApplyPilot?style=social)](https://github.com/Pickle-Pixel/ApplyPilot)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/S6S01UL5IO)




https://github.com/user-attachments/assets/7ee3417f-43d4-4245-9952-35df1e77f2df


---

## What It Does

ApplyPilot is a 6-stage autonomous job application pipeline. It discovers jobs across 5+ boards, scores them against your resume with AI, tailors your resume per job, writes cover letters, and **submits applications for you**. It navigates forms, uploads documents, answers screening questions, all hands-free.

Three commands. That's it.

```bash
pip install applypilot
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
playwright install chromium   # browser used for enrichment, direct-site discovery and PDFs
applypilot init          # one-time setup: resume, profile, preferences, API keys
applypilot doctor        # verify your setup — shows what's installed and what's missing
applypilot run           # discover > enrich > score > tailor > cover letters
applypilot run -w 4      # same but parallel (4 threads for discovery/enrichment)
applypilot apply         # autonomous browser-driven submission
applypilot apply -w 3    # parallel apply (3 Chrome instances)
applypilot apply --dry-run  # fill forms without submitting
```

> **Why two install commands?** `python-jobspy` pins an exact numpy version in its metadata that conflicts with pip's resolver, but works fine at runtime with any modern numpy. The `--no-deps` flag bypasses the resolver; the second command installs jobspy's actual runtime dependencies. Everything except `python-jobspy` installs normally. pip may also warn that jobspy wants `pandas<3` / an older `regex`; discovery works with the current versions, so the warning can be ignored.

---

## Two Paths

### Full Pipeline (recommended)
**Requires:** Python 3.11+, Node.js (for npx), Gemini API key (free), Claude Code CLI, Chrome

Runs all 6 stages, from job discovery to autonomous application submission. This is the full power of ApplyPilot.

### Discovery + Tailoring Only
**Requires:** Python 3.11+, Gemini API key (free)

Runs stages 1-5: discovers jobs, scores them, tailors your resume, generates cover letters. You submit applications manually with the AI-prepared materials.

---

## The Pipeline

| Stage | What Happens |
|-------|-------------|
| **1. Discover** | Scrapes 5 job boards (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs) + 48 Workday employer portals + 30 direct career sites |
| **2. Enrich** | Fetches full job descriptions via JSON-LD, CSS selectors, or AI-powered extraction |
| **3. Score** | AI rates every job 1-10 based on your resume and preferences. Only high-fit jobs proceed |
| **4. Tailor** | AI rewrites your resume per job: reorganizes, emphasizes relevant experience, adds keywords. Never fabricates |
| **5. Cover Letter** | AI generates a targeted cover letter per job |
| **6. Auto-Apply** | Claude Code navigates application forms, fills fields, uploads documents, answers questions, and submits |

Each stage is independent. Run them all or pick what you need.

---

## ApplyPilot vs The Alternatives

| Feature | ApplyPilot | AIHawk | Manual |
|---------|-----------|--------|--------|
| Job discovery | 5 boards + Workday + direct sites | LinkedIn only | One board at a time |
| AI scoring | 1-10 fit score per job | Basic filtering | Your gut feeling |
| Resume tailoring | Per-job AI rewrite | Template-based | Hours per application |
| Auto-apply | Full form navigation + submission | LinkedIn Easy Apply only | Click, type, repeat |
| Supported sites | Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs, 46 Workday portals, 28 direct sites | LinkedIn | Whatever you open |
| License | AGPL-3.0 | MIT | N/A |

---

## Requirements

| Component | Required For | Details |
|-----------|-------------|---------|
| Python 3.11+ | Everything | Core runtime |
| Playwright Chromium | Enrichment, direct-site discovery, PDFs | `playwright install chromium` (one-time download) |
| Node.js 18+ | Auto-apply | Needed for `npx` to run Playwright MCP server |
| Gemini API key | Scoring, tailoring, cover letters | Free tier (15 RPM / 1M tokens/day) is enough |
| Chrome/Chromium | Auto-apply | Auto-detected on most systems |
| Claude Code CLI | Auto-apply | Install from [claude.ai/code](https://claude.ai/code) |

**Gemini API key is free.** Get one at [aistudio.google.com](https://aistudio.google.com). OpenAI and local models (Ollama/llama.cpp) are also supported.

### Optional

| Component | What It Does |
|-----------|-------------|
| CapSolver API key | Solves CAPTCHAs during auto-apply (hCaptcha, reCAPTCHA, Turnstile, FunCaptcha). Without it, CAPTCHA-blocked applications just fail gracefully |

> **Note:** python-jobspy is installed separately with `--no-deps` because it pins an exact numpy version in its metadata that conflicts with pip's resolver. It works fine with modern numpy at runtime.

---

## Configuration

All generated by `applypilot init` or the web UI's **Setup** page, and stored in `~/.applypilot/` (override with the `APPLYPILOT_DIR` environment variable):

### `profile.json`
Your personal data in one structured file: contact info, work authorization, compensation, experience, skills, resume facts (preserved during tailoring), and EEO defaults. Powers scoring, tailoring, and form auto-fill.

### `searches.yaml`
Job search queries, target titles, locations, boards. Run multiple searches with different parameters.
The keys discovery actually reads: `queries` (`query` + `tier`), `locations` (`location` + `remote`), `sites` (boards), `location_accept` / `location_reject_non_remote` (location filter for non-remote jobs) and `defaults` (`results_per_site`, `hours_old`, `country_indeed`). With an empty `location_accept`, every onsite/hybrid job is dropped and only remote jobs are kept.

### `.env`
API keys and runtime config: `GEMINI_API_KEY`, `LLM_MODEL`, `CAPSOLVER_API_KEY` (optional).

### `applications/`
One folder per job with everything generated for it: `resume.txt`/`.pdf`, `cover_letter.txt`/`.pdf`, a copy of the posting (`job.txt`) and the tailoring report. Folder names include a short hash of the job URL, so postings with the same title never overwrite each other.

### Package configs (shipped with ApplyPilot)
- `config/employers.yaml` - Workday employer registry (48 preconfigured)
- `config/sites.yaml` - Direct career sites (30+), blocked sites, base URLs, manual ATS domains
- `config/searches.example.yaml` - Example search configuration

---

## How Stages Work

### Discover
Queries Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs via JobSpy. Scrapes 48 Workday employer portals (configurable in `employers.yaml`). Hits 30 direct career sites with custom extractors. Deduplicates by URL.

### Enrich
Visits each job URL and extracts the full description. 3-tier cascade: JSON-LD structured data, then CSS selector patterns, then AI-powered extraction for unknown layouts.

### Score
AI scores every job 1-10 against your profile. 9-10 = strong match, 7-8 = good, 5-6 = moderate, 1-4 = skip. Only jobs above your threshold proceed to tailoring.

### Tailor
Generates a custom resume per job: reorders experience, emphasizes relevant skills, incorporates keywords from the job description. Your `resume_facts` (companies, projects, metrics) are preserved exactly. The AI reorganizes but never fabricates.

### Cover Letter
Writes a targeted cover letter per job referencing the specific company, role, and how your experience maps to their requirements.

### Auto-Apply
Claude Code launches a Chrome instance, navigates to each application page, detects the form type, fills personal information and work history, uploads the tailored resume and cover letter, answers screening questions with AI, and submits. A live dashboard shows progress in real-time.

The Playwright MCP server is configured automatically at runtime per worker. No manual MCP setup needed.

```bash
# Utility modes (no Chrome/Claude needed)
applypilot apply --mark-applied URL    # manually mark a job as applied
applypilot apply --mark-failed URL     # manually mark a job as failed
applypilot apply --reset-failed        # reset all failed jobs for retry
applypilot apply --gen --url URL       # generate prompt file for manual debugging
```

---

## Web UI (local)

A browser interface for everything except auto-apply: configure your profile and searches, launch pipeline stages and follow their output live, then review jobs with their tailored resume and cover letter.

### Install from source

Requires Python 3.11+ and Git. Windows (PowerShell):

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

> If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and call `.venv\Scripts\applypilot ui` directly.

### First run

1. **Setup**: fill in your profile, paste your resume as plain text, define your searches, and add an AI key. Use **Probar conexión** to check the key and model before saving. The model field needs the technical ID (e.g. `gemini-2.5-flash`), not the marketing name; a failed test lists the models your key can use.
2. **Pipeline**: run **Buscar ofertas nuevas** (discover + enrich), then **Procesar con IA** (score, tailor, cover letters, PDFs).
3. **Ofertas**: filter by status, score band (7+, 5–6, 4 or less, unscored) and board; open a job to read why it got its score, its tailored resume and cover letter; mark it as applied or discard it. **Abrir carpeta** opens the job's folder in `applications/`.
4. **Bulk actions**: tick rows (or the header box for the whole page, then **Seleccionar las N que coinciden** for every page) to discard or mark many jobs at once. Each bulk action can be undone right after.

**Inicio** (home) shows how your search is going, from jobs found to applications sent, the best-scored jobs waiting for review, and the last pipeline run.

### Good to know

- The server only listens on `127.0.0.1` and rejects requests from other sites. API keys are never sent back to the browser in full.
- One pipeline run at a time. Each run is the regular `applypilot run ...` command in the background, with its full output saved to `~/.applypilot/logs/ui-run-*.log`. **Detener** stops it; closing the terminal stops it too. Work finished before stopping is kept.
- Discarded jobs are skipped by every stage (enrich, score, tailor, cover, apply) and stay in the database, so later searches recognize them and don't add them again. Discarding is not deleting.
- The UI and the CLI share the same files and database, so you can mix them.
- Auto-apply is not in the UI; use `applypilot apply` from the terminal if you want it.

### Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Scoring stops with `HTTP 400: ... unexpected model name format` | Wrong model name in **Claves de IA**. Use the technical ID; **Probar conexión** lists valid ones. |
| `HTTP 503` / `HTTP 429` from the AI provider | Provider busy or free-tier limit reached. The pipeline retries with backoff; try later or pick another model. |
| `ZipRecruiter response status code 403` in the log | ZipRecruiter only serves the US and Canada. Untick it in **Búsquedas**. |
| `Glassdoor: location not parsed` | Glassdoor doesn't recognize that location. The other boards still run. |
| Only remote jobs show up | `location_accept` is empty: add your cities in **Búsquedas → Filtro de ubicación**. |

---

## Changes in this fork

Besides the web UI (`src/applypilot/ui/`, `applypilot ui`):

- **Company name**: JobSpy's company was read and thrown away, and every prompt (scoring, tailoring, cover letters, auto-apply) received the job board as the company (`COMPANY: linkedin`). The company is now stored and used; jobs found earlier get it the next time discovery sees them.
- **Per-application folders** (`applications/`): jobs with the same title and site no longer overwrite each other's resume and cover letter (which also left the database pointing at the wrong file for auto-apply).
- **Discarded jobs**: new `discarded_at` column; every stage skips discarded jobs. `run --stream` pending counts skip them too, so it can't loop forever.
- **Scoring errors**: failed LLM calls are no longer saved as a score of 0 (which marked jobs as scored forever); they stay pending and are retried. Scoring stops after 3 consecutive failures and reports the reason. Existing fake zeros are cleared on startup.
- **LLM errors** include the provider's message instead of a bare `400 Bad Request`.
- **Search config**: the example config and the UI use the keys discovery reads (`sites`, `location_accept`, `location_reject_non_remote`, `defaults.country_indeed`). The old example used `boards` and `location.accept_patterns`, which discovery ignored.
- **PDF stage** converts files found through the database, including cover letters (previously only resumes in the flat folder).
- `applypilot doctor` checks moved to `applypilot/checks.py` (shared with the UI); output unchanged.
- First test suite (`pytest tests/`).

---

## CLI Reference

```
applypilot init                         # First-time setup wizard
applypilot doctor                       # Verify setup, diagnose missing requirements
applypilot run [stages...]              # Run pipeline stages (or 'all')
applypilot run --workers 4              # Parallel discovery/enrichment
applypilot run --stream                 # Concurrent stages (streaming mode)
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
applypilot status                       # Pipeline statistics
applypilot dashboard                    # Open HTML results dashboard
applypilot ui                           # Local web UI (this fork; see "Web UI")
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR guidelines.

---

## License

ApplyPilot is licensed under the [GNU Affero General Public License v3.0](LICENSE).

You are free to use, modify, and distribute this software. If you deploy a modified version as a service, you must release your source code under the same license.
