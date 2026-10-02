"""Backend seam to the EXTERNAL Code runner (sprint-4/19 S4, D20).

The application never executes builder Python. ``code.run`` submits a job to
the separately deployed runner over authenticated HTTP and consumes its
result. Tests inject a fake through :func:`use_code_runner_client`.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Protocol


class CodeRunnerUnavailable(RuntimeError):
    """The runner could not be reached or refused the job transport."""


@dataclass
class CodeRunResult:
    ok: bool
    termination: str
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    console_truncated: bool = False
    duration_ms: int = 0
    runner_version: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, payload: Dict[str, Any]) -> "CodeRunResult":
        return cls(
            ok=bool(payload.get("ok")),
            termination=str(payload.get("termination") or ("completed" if payload.get("ok") else "error")),
            result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
            error=str(payload.get("error") or ""),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            console_truncated=bool(payload.get("consoleTruncated")),
            duration_ms=int(payload.get("durationMs") or 0),
            runner_version=str(payload.get("runnerVersion") or ""),
        )


class CodeRunnerClient(Protocol):
    def run(self, source: str, inputs: Dict[str, Any]) -> CodeRunResult: ...

    def health(self) -> bool: ...


class HttpCodeRunnerClient:
    """Production transport. Auth = bearer token; transport details never
    surface in run logs (callers map failures to generic messages)."""

    def __init__(self, base_url: str, token: str = "", timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": "Foundryx-Workflow/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def run(self, source: str, inputs: Dict[str, Any]) -> CodeRunResult:
        body = json.dumps({"source": source, "input": inputs}).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}/run", data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - internal URL from settings
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CodeRunnerUnavailable(f"runner rejected the job ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise CodeRunnerUnavailable("runner unreachable") from exc
        if not isinstance(payload, dict):
            raise CodeRunnerUnavailable("runner returned an invalid response")
        return CodeRunResult.from_wire(payload)

    def health(self) -> bool:
        # Bearer included: "healthy" means the runner is up AND accepts OUR
        # token (a 401 here surfaces a token mismatch at publish, not at run).
        request = urllib.request.Request(f"{self.base_url}/health", headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout_seconds, 3.0)) as response:  # noqa: S310
                return response.status == 200
        except Exception:  # noqa: BLE001
            return False


_client_override: Any = None
_health_cache: Dict[str, Any] = {"at": 0.0, "value": False}
_health_lock = threading.Lock()
HEALTH_CACHE_SECONDS = 10.0


def get_code_runner_client() -> Optional[CodeRunnerClient]:
    """None = no runner configured (the capability is absent, not broken)."""
    if _client_override is not None:
        return _client_override
    from app.config import settings

    url = (settings.code_runner_url or "").strip()
    if not url:
        return None
    return HttpCodeRunnerClient(url, settings.code_runner_token or "", settings.code_runner_timeout_seconds)


@contextlib.contextmanager
def use_code_runner_client(client: Any) -> Iterator[None]:
    """Test seam: inject a fake (or ``False`` to simulate 'not configured')."""
    global _client_override
    previous = _client_override
    _client_override = client
    reset_health_cache()
    try:
        yield
    finally:
        _client_override = previous
        reset_health_cache()


def reset_health_cache() -> None:
    with _health_lock:
        _health_cache["at"] = 0.0
        _health_cache["value"] = False


def code_runner_available(*, force: bool = False) -> bool:
    """Cached health probe (drives the editor warning + publish gate)."""
    client = get_code_runner_client()
    if client is None or client is False:
        return False
    now = time.monotonic()
    with _health_lock:
        if not force and now - _health_cache["at"] < HEALTH_CACHE_SECONDS:
            return bool(_health_cache["value"])
    try:
        value = bool(client.health())
    except Exception:  # noqa: BLE001
        value = False
    with _health_lock:
        _health_cache["at"] = now
        _health_cache["value"] = value
    return value
