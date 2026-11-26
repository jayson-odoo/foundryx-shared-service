"""The pull worker: health gate -> claim -> download inputs -> run the engine in
a capped child -> upload outputs -> finish. One job at a time.

Every call carries ``Authorization: Bearer <token>`` and
``X-Planner3d-Worker: <name>``. The token is only ever placed in that header;
it is never logged, never in an error message.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import httpx

from planner3d_worker.health import can_start, free_ram_mb, swap_used_pct
from planner3d_worker.runner import JobCancelled, JobTimeout, MemoryCapExceeded, run_capped

log = logging.getLogger("planner3d_worker")

BASE = "/planner3d/worker"
DEFAULT_RSS_CAP_MB = 8192
DEFAULT_TIMEOUT_S = 1800
HEARTBEAT_S = 15
LOCAL_HOSTS = ("localhost", "127.0.0.1", "testserver")
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")

# What SS is told when a job fails: short, generic, no paths or library text.
# The raw exception goes to the local log only.
GENERIC_ERRORS = {
    "worker_failed": "The worker could not complete the job.",
    "memory_cap": "The job used more memory than allowed.",
    "timeout": "The job took longer than allowed.",
    "bad_input": "The job inputs were not valid.",
}


def _check_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme == "https":
        return
    host = parsed.hostname or ""
    # ".test" is a reserved name that never resolves on the public internet.
    if parsed.scheme == "http" and (host in LOCAL_HOSTS or host.endswith(".test")):
        return
    raise ValueError("base_url must be https (plain http only for localhost)")


def _is_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def _safe_name(name: object) -> bool:
    return isinstance(name, str) and SAFE_NAME.fullmatch(name) is not None and ".." not in name


class Cancelled(Exception):
    """SS answered a heartbeat with 409 cancelled: stop, do not finish."""


def system_health() -> tuple[bool, str]:
    return can_start(swap_used_pct(), free_ram_mb())


def _engine_target(engine, kind: str, inputs: dict, params: dict, out_dir: str):
    """Module level so the spawned child can unpickle it."""
    return engine.run(kind, inputs, params, out_dir)


class Worker:
    def __init__(
        self,
        base_url: str,
        token: str,
        name: str,
        engine,
        http: Optional[httpx.Client] = None,
        work_dir: Optional[Path] = None,
        health: Callable[[], tuple[bool, str]] = system_health,
        rss_cap_mb: float = DEFAULT_RSS_CAP_MB,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        heartbeat_s: float = HEARTBEAT_S,
    ):
        _check_base_url(base_url)
        self.name = name
        self.engine = engine
        self.health = health
        self.rss_cap_mb = rss_cap_mb
        self.timeout_s = timeout_s
        self.heartbeat_s = heartbeat_s
        self.work_dir = Path(work_dir) if work_dir else Path.home() / "planner3d" / "work"
        self._headers = {"Authorization": f"Bearer {token}", "X-Planner3d-Worker": name}
        self._http = http or httpx.Client(base_url=base_url, timeout=60.0)

    # ── http ────────────────────────────────────────────────────────────────

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        return self._http.request(method, f"{BASE}{path}", headers=self._headers, **kw)

    def _heartbeat(self, job_id: str, progress: Optional[int] = None) -> None:
        res = self._req("POST", f"/jobs/{job_id}/heartbeat", json={"progress": progress})
        if res.status_code == 409:
            raise Cancelled()
        res.raise_for_status()

    # ── one job ─────────────────────────────────────────────────────────────

    def run_once(self) -> Optional[str]:
        """Handle at most one job. Returns the job id, or None when idle,
        refused by the health gate, or unable to reach SS."""
        ok, reason = self.health()
        if not ok:
            log.info("not claiming: %s", reason)
            return None
        try:
            res = self._req("POST", "/claim", json={"kinds": list(self.engine.kinds)})
            if res.status_code == 204:
                return None
            res.raise_for_status()
            job = res.json()
        except httpx.HTTPError as exc:
            log.warning("claim failed: %s", type(exc).__name__)
            return None

        job_id, kind = job.get("jobId"), job.get("kind")
        if not _is_uuid(job_id):
            log.warning("ignoring a claim whose job id is not a UUID")
            return None
        job_dir = self.work_dir / job_id
        try:
            self._process(job_id, kind, job.get("params") or {}, job.get("inputs") or [], job_dir)
        except Cancelled:
            log.info("job %s was cancelled; stopping", job_id)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        return job_id

    def _process(self, job_id: str, kind: str, params: dict, inputs: list, job_dir: Path) -> None:
        in_dir, out_dir = job_dir / "in", job_dir / "out"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        self._heartbeat(job_id, 0)
        root = in_dir.resolve()
        for item in inputs:
            name = item.get("name")
            if not _safe_name(name) or not (root / name).resolve().is_relative_to(root):
                self._finish_failed(job_id, "bad_input", "an input name was rejected")
                return
        try:
            paths = {}
            for item in inputs:
                got = self._req("GET", f"/jobs/{job_id}/inputs/{item['name']}")
                got.raise_for_status()
                path = in_dir / item["name"]
                path.write_bytes(got.content)
                paths[item["name"]] = str(path)
        except httpx.HTTPError as exc:
            self._finish_failed(job_id, "worker_failed", f"input download failed: {type(exc).__name__}")
            return

        try:
            produced, peak, seconds = self._run_engine(job_id, kind, paths, params, out_dir)
        except MemoryCapExceeded as exc:
            self._finish_failed(job_id, "memory_cap", str(exc))
            return
        except JobTimeout as exc:
            self._finish_failed(job_id, "timeout", str(exc))
            return
        except JobCancelled:
            raise Cancelled()
        except Exception as exc:  # noqa: BLE001 - any engine failure is reported, not raised
            self._finish_failed(job_id, "worker_failed", str(exc) or type(exc).__name__)
            return

        self._heartbeat(job_id, 90)
        try:
            for name, role in produced:
                put = self._req(
                    "PUT",
                    f"/jobs/{job_id}/outputs/{name}",
                    params={"role": role},
                    content=(out_dir / name).read_bytes(),
                )
                put.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            self._finish_failed(job_id, "worker_failed", f"upload failed: {type(exc).__name__}")
            return
        self._finish(job_id, {"status": "succeeded", "gpuSeconds": round(seconds, 2), "peakRssMb": round(peak, 1)})

    def _run_engine(self, job_id: str, kind: str, paths: dict, params: dict, out_dir: Path):
        """The engine runs in a capped child; this thread keeps the lease alive
        and stops the child when SS says the job was cancelled."""
        cancel = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                run_capped,
                _engine_target,
                (self.engine, kind, paths, params, str(out_dir)),
                self.rss_cap_mb,
                self.timeout_s,
                cancel,
            )
            cancelled = False
            while True:
                try:
                    return future.result(timeout=self.heartbeat_s)
                except TimeoutError:
                    pass
                except Exception:
                    if cancelled:
                        raise JobCancelled("job cancelled")
                    raise
                try:
                    self._heartbeat(job_id)
                except Cancelled:
                    cancelled = True
                    cancel.set()
                except httpx.HTTPError:
                    log.warning("heartbeat failed for %s", job_id)

    # ── finishing ───────────────────────────────────────────────────────────

    def _finish_failed(self, job_id: str, code: str, detail: str) -> None:
        log.warning("job %s failed (%s): %s", job_id, code, detail)
        message = GENERIC_ERRORS.get(code, GENERIC_ERRORS["worker_failed"])
        self._finish(job_id, {"status": "failed", "error": {"code": code, "message": message}})

    def _finish(self, job_id: str, body: dict) -> None:
        body.setdefault("gpuSeconds", 0)
        body.setdefault("peakRssMb", 0)
        try:
            self._req("POST", f"/jobs/{job_id}/finish", json=body).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("finish failed for %s: %s", job_id, type(exc).__name__)

    # ── loop ────────────────────────────────────────────────────────────────

    def run_loop(self, idle_sleep_s: float = 10.0, stop: Optional[threading.Event] = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                handled = self.run_once()
            except Exception:  # noqa: BLE001 - the loop must survive any one job
                log.exception("job handling failed")
                handled = None
            if handled is None:
                stop.wait(idle_sleep_s)
