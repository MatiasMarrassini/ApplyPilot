"""Run ``applypilot`` CLI commands as a background subprocess and capture their output.

The UI never calls pipeline functions in-process: they print to a Rich
console, may raise SystemExit, and can run for hours. A subprocess keeps the
server responsive, gives us the exact CLI behaviour, and can be killed.

Only one run at a time — every stage writes to the same database.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from applypilot import config

MAX_LINES = 3000


@dataclass
class Run:
    title: str
    args: list[str]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    returncode: int | None = None
    cancelled: bool = False
    lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LINES))
    log_path: str = ""

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def status(self) -> str:
        if self.running:
            return "running"
        if self.cancelled:
            return "cancelled"
        return "ok" if self.returncode == 0 else "error"

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def command(self) -> str:
        return "applypilot " + " ".join(self.args)


class Runner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.current: Run | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.running

    def start(self, title: str, args: list[str]) -> Run:
        with self._lock:
            if self.busy:
                raise RuntimeError("Ya hay una ejecución en curso")

            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")  # local time, for the file name
            run = Run(title=title, args=args, log_path=str(config.LOG_DIR / f"ui-run-{stamp}.log"))

            env = os.environ.copy()
            env.update({
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",  # Rich prints characters cp1252 can't encode
                "COLUMNS": "140",
                "NO_COLOR": "1",
            })
            kwargs: dict = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True

            self._proc = subprocess.Popen(
                [sys.executable, "-m", "applypilot", *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **kwargs,
            )
            self.current = run
            threading.Thread(target=self._pump, args=(self._proc, run), daemon=True).start()
            return run

    def _pump(self, proc: subprocess.Popen, run: Run) -> None:
        with open(run.log_path, "w", encoding="utf-8") as log:
            log.write(f"$ {run.command}\n")
            for line in proc.stdout:
                line = line.rstrip("\n")
                run.lines.append(line)
                log.write(line + "\n")
                log.flush()
            run.returncode = proc.wait()
        run.finished_at = time.time()

    def stop(self) -> None:
        with self._lock:
            if not self.busy or self._proc is None:
                return
            self.current.cancelled = True
            _kill_tree(self._proc.pid)


def _kill_tree(pid: int) -> None:
    """Kill the run and its children (enrichment/discovery launch browsers)."""
    import signal

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


runner = Runner()


@atexit.register
def _stop_on_exit() -> None:
    # Don't leave a scraper running after the UI server is closed.
    runner.stop()
