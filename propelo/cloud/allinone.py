"""One server instead of three (ALL_IN_ONE=on).

The usual deployment has a release step (`propelo cloud migrate`), a web service and a worker service.
A host's free or smallest tier often allows only a single web service, so with ALL_IN_ONE=on
`propelo cloud serve` does all three: it brings the database up to date, then runs the worker as a
child process beside the web app and starts it again if it stops. One instance only: two would both
try to migrate. Move to separate services when there is more than one web instance.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

from .config import Config
from .db import Database


def prepare(cfg: Config) -> Database:
    """Check the settings, connect and apply pending migrations. Returns the database the web app will use."""
    problems = cfg.check()
    if problems:
        raise SystemExit("Unsafe configuration:\n- " + "\n- ".join(problems))
    db = Database(cfg.database_url, cfg.db_pool_min, cfg.db_pool_max)
    try:
        applied = db.migrate(log=lambda m: print(m, flush=True))
    except BaseException:
        db.close()
        raise
    print(f"{len(applied)} migration(s) applied." if applied else "Database is up to date.", flush=True)
    return db


class WorkerChild:
    """Runs `propelo cloud worker` as a child process and restarts it, waiting longer after quick failures."""

    def __init__(self, command: list[str] | None = None, base_delay: float = 2.0):
        self.command = command or [sys.executable, "-m", "propelo", "cloud", "worker"]
        self.base_delay = base_delay
        self.stop = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.starts = 0
        self._thread: threading.Thread | None = None

    def wake(self) -> None:
        """Tell a sleeping worker there is a new task (it sleeps long when idle so the database can pause)."""
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.send_signal(signal.SIGUSR1)
            except (OSError, ValueError, AttributeError):
                pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="worker-child", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        delay = self.base_delay
        while not self.stop.is_set():
            began = time.monotonic()
            try:
                self.proc = subprocess.Popen(self.command, preexec_fn=_die_with_parent if sys.platform == "linux" else None,
                                             env=dict(os.environ, PROPELO_WORKER_WAKE="signal"))
            except OSError as e:
                print(f"worker could not start: {e}", flush=True)
                self.stop.wait(60)
                continue
            self.starts += 1
            code = self.proc.wait()
            if self.stop.is_set():
                return
            delay = self.base_delay if time.monotonic() - began > 60 else min(delay * 2, 60.0)
            print(f"worker stopped with status {code}; starting it again in {delay:.0f}s", flush=True)
            self.stop.wait(delay)

    def close(self, wait: float = 10.0) -> None:
        self.stop.set()
        p = self.proc
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(wait)
            except subprocess.TimeoutExpired:
                p.kill()
        if self._thread is not None:
            self._thread.join(2)


def _die_with_parent() -> None:
    """Runs in the child before it starts: ask Linux to stop it if the web process is killed outright."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001 - a missing libc must not stop the worker from starting
        pass


def serve(cfg: Config, host: str, port: int) -> None:
    import uvicorn

    from .app import create_app
    db = prepare(cfg)
    child = WorkerChild()
    child.start()
    from . import repo
    repo.on_enqueue = child.wake  # a sign-in email or a new search starts at once, even when the worker sleeps

    def finish(*_):
        child.close()
        raise SystemExit(0)
    try:
        # The web server handles the stop signal itself, shuts down, then passes the signal on to this handler.
        signal.signal(signal.SIGTERM, finish)
    except (ValueError, OSError):
        pass
    try:
        uvicorn.run(create_app(cfg, db=db), host=host, port=port, proxy_headers=cfg.trust_proxy, forwarded_allow_ips="*" if cfg.trust_proxy else None)
    finally:
        child.close()
        db.close()
