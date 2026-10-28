# Changelog

All notable changes to ApplyPilot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - Web UI fork

Changes in [this fork](https://github.com/MatiasMarrassini/ApplyPilot) on top of the original 0.3.0.

### Added
- **Local web UI** (`src/applypilot/ui/`, `applypilot ui`): setup forms (profile, resume,
  searches, AI keys with a connection test), pipeline runner with live logs, job list with
  filters and undoable bulk actions, job detail view, and a home page with search progress.
- **Argentina and Latin America sources**: built-in extractors for Computrabajo, EmpleosIT
  (Argentina) and GetOnBoard (Latin America, official API). They need no AI: GetOnBoard and
  EmpleosIT bring the full description, and Computrabajo's detail pages are read from their
  structured data. They start disabled; turn them on in Setup > Portales.
- **Choosing sources**: each source has a group (`group:` in `config/sites.yaml` and
  `config/employers.yaml`) and can be turned off; choices are stored under `sources` in
  `searches.yaml`. Discovery used to run every Workday portal and direct site on each search.
- **Documents in the job's language**: the tailored resume and cover letter are written in the
  posting's language (Spanish or English, detected automatically; can be pinned in
  Setup > Perfil > Documentos). Section titles, PDF headings and the letter greeting follow
  the language, and the fabrication judge treats translation as allowed.
- **Location-aware scoring**: the scorer knows where the candidate lives and whether they need
  sponsorship. Remote jobs restricted to another country (e.g. "US only") score at most 3,
  onsite/hybrid elsewhere at most 4. The explanation is written in Spanish for the UI.
- **Discarded jobs**: new `discarded_at` column; every stage skips discarded jobs.
- First test suite (`pytest tests/`).

### Fixed
- **Company name**: JobSpy's company was read and thrown away, and every prompt (scoring,
  tailoring, cover letters, auto-apply) received the job board as the company
  (`COMPANY: linkedin`). The company is now stored and used; jobs found earlier get it the
  next time discovery sees them.
- **Location filter** recognizes Spanish remote wording ("remoto", "teletrabajo", "home office").
- **Fabrication watchlist**: generic "suspicious" skills (Django, Angular, Spring, ...) no
  longer count as invented when they are in the user's own skills.
- **Per-application folders** (`applications/`): jobs with the same title and site no longer
  overwrite each other's resume and cover letter (which also left the database pointing at
  the wrong file for auto-apply).
- **`run --stream`** pending counts skip discarded jobs, so it can't loop forever.
- **Scoring errors**: failed LLM calls are no longer saved as a score of 0 (which marked jobs
  as scored forever); they stay pending and are retried. Scoring stops after 3 consecutive
  failures and reports the reason. Existing fake zeros are cleared on startup.
- **LLM errors** include the provider's message instead of a bare `400 Bad Request`.
- **Search config**: the example config and the UI use the keys discovery reads (`sites`,
  `location_accept`, `location_reject_non_remote`, `defaults.country_indeed`). The old
  example used `boards` and `location.accept_patterns`, which discovery ignored.
- **PDF stage** converts files found through the database, including cover letters
  (previously only resumes in the flat folder).
- **"database is locked"** after resetting failed scores: the reset is now always committed.

### Changed
- `applypilot doctor` checks moved to `applypilot/checks.py` (shared with the UI); output
  unchanged.

## [0.2.0] - 2026-02-17

### Added
- **Parallel workers for discovery/enrichment** - `applypilot run --workers N` enables
  ThreadPoolExecutor-based parallelism for Workday scraping, smart extract, and detail
  enrichment. Default is sequential (1); power users can scale up.
- **Apply utility modes** - `--gen` (generate prompt for manual debugging), `--mark-applied`,
  `--mark-failed`, `--reset-failed` flags on `applypilot apply`
- **Dry-run mode** - `applypilot apply --dry-run` fills forms without clicking Submit
- **5 new tracking columns** - `agent_id`, `last_attempted_at`, `apply_duration_ms`,
  `apply_task_id`, `verification_confidence` for better apply-stage observability
- **Manual ATS detection** - `manual_ats` list in `config/sites.yaml` skips sites with
  unsolvable CAPTCHAs (e.g. TCS iBegin)
- **Qwen3 `/no_think` optimization** - automatically saves tokens when using Qwen models
- **`config.DEFAULTS`** - centralized dict for magic numbers (`min_score`, `max_apply_attempts`,
  `poll_interval`, `apply_timeout`, `viewport`)

### Fixed
- **Config YAML not found after install** - moved `config/` into the package at
  `src/applypilot/config/` so YAML files (employers, sites, searches) ship with `pip install`
- **Search config format mismatch** - wizard wrote `searches:` key but discovery code
  expected `queries:` with tier support. Aligned wizard output and example config
- **JobSpy install isolation** - removed python-jobspy from package dependencies due to
  broken numpy==1.26.3 exact pin in jobspy metadata. Installed separately with `--no-deps`
- **Scoring batch limit** - default limit of 50 silently left jobs unscored across runs.
  Changed to no limit (scores all pending jobs in one pass)
- **Missing logging output** - added `logging.basicConfig(INFO)` so per-job progress for
  scoring, tailoring, and cover letters is visible during pipeline runs

### Changed
- **Blocked sites externalized** - moved from hardcoded sets in launcher.py to
  `config/sites.yaml` under `blocked:` key
- **Site base URLs externalized** - moved from hardcoded dict in detail.py to
  `config/sites.yaml` under `base_urls:` key
- **SSO domains externalized** - moved from hardcoded list in prompt.py to
  `config/sites.yaml` under `blocked_sso:` key
- **Prompt improvements** - screening context uses `target_role` from profile,
  salary section includes `currency_conversion_note` and dynamic hourly rate examples
- **`acquire_job()` fixed** - writes `agent_id` and `last_attempted_at` to proper columns
  instead of misusing `apply_error`
- **`profile.example.json`** - added `currency_conversion_note` and `target_role` fields

## [0.1.0] - 2026-02-17

### Added
- 6-stage pipeline: discover, enrich, score, tailor, cover letter, apply
- Multi-source job discovery: Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs
- Workday employer portal support (46 preconfigured employers)
- Direct career site scraping (28 preconfigured sites)
- 3-tier job description extraction cascade (JSON-LD, CSS selectors, AI fallback)
- AI-powered job scoring (1-10 fit scale with rationale)
- Resume tailoring with factual preservation (no fabrication)
- Cover letter generation per job
- Autonomous browser-based application submission via Playwright
- Interactive setup wizard (`applypilot init`)
- Cross-platform Chrome/Chromium detection (Windows, macOS, Linux)
- Multi-provider LLM support (Gemini, OpenAI, local models via OpenAI-compatible endpoints)
- Pipeline stats and HTML results dashboard
- YAML-based configuration for employers, career sites, and search queries
- Job deduplication across sources
- Configurable score threshold filtering
- Safety limits for maximum applications per run
- Detailed application results logging
