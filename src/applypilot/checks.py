"""Setup checks shared by ``applypilot doctor`` and the web UI."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "missing" | "optional"
    note: str


def run_checks() -> list[Check]:
    """Inspect the local setup and return one Check per requirement."""
    from applypilot.config import (
        PROFILE_PATH,
        RESUME_PATH,
        RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH,
        get_chrome_path,
        load_env,
    )

    load_env()
    results: list[Check] = []

    # --- Tier 1 ---
    if PROFILE_PATH.exists():
        results.append(Check("profile.json", "ok", str(PROFILE_PATH)))
    else:
        results.append(Check("profile.json", "missing", "Run 'applypilot init' to create"))

    if RESUME_PATH.exists():
        results.append(Check("resume.txt", "ok", str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(Check("resume.txt", "warn", "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(Check("resume.txt", "missing", "Run 'applypilot init' to add your resume"))

    if SEARCH_CONFIG_PATH.exists():
        results.append(Check("searches.yaml", "ok", str(SEARCH_CONFIG_PATH)))
    else:
        results.append(Check("searches.yaml", "warn", "Will use example config — run 'applypilot init'"))

    try:
        import jobspy  # noqa: F401
        results.append(Check("python-jobspy", "ok", "Job board scraping available"))
    except ImportError:
        results.append(Check(
            "python-jobspy", "warn",
            "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex",
        ))

    # --- Tier 2 ---
    if os.environ.get("GEMINI_API_KEY"):
        results.append(Check("LLM API key", "ok", f"Gemini ({os.environ.get('LLM_MODEL', 'gemini-2.0-flash')})"))
    elif os.environ.get("OPENAI_API_KEY"):
        results.append(Check("LLM API key", "ok", f"OpenAI ({os.environ.get('LLM_MODEL', 'gpt-4o-mini')})"))
    elif os.environ.get("LLM_URL"):
        results.append(Check("LLM API key", "ok", f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(Check("LLM API key", "missing",
                             "Set GEMINI_API_KEY in ~/.applypilot/.env (run 'applypilot init')"))

    # --- Tier 3 ---
    claude_bin = shutil.which("claude")
    if claude_bin:
        results.append(Check("Claude Code CLI", "ok", claude_bin))
    else:
        results.append(Check("Claude Code CLI", "missing",
                             "Install from https://claude.ai/code (needed for auto-apply)"))

    try:
        results.append(Check("Chrome/Chromium", "ok", get_chrome_path()))
    except FileNotFoundError:
        results.append(Check("Chrome/Chromium", "missing",
                             "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(Check("Node.js (npx)", "ok", npx_bin))
    else:
        results.append(Check("Node.js (npx)", "missing",
                             "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    if os.environ.get("CAPSOLVER_API_KEY"):
        results.append(Check("CapSolver API key", "ok", "CAPTCHA solving enabled"))
    else:
        results.append(Check("CapSolver API key", "optional",
                             "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    return results
