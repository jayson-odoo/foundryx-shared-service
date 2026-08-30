"""Minimal authenticated HTTP surface: ``GET /health`` and ``POST /run``.

Stdlib only. Bearer auth via ``CODE_RUNNER_TOKEN`` (required unless
``CODE_RUNNER_ALLOW_ANONYMOUS=1`` - local development only). One semaphore
bounds concurrent sandboxes.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from code_runner import RUNNER_VERSION
from code_runner.sandbox import Limits, execute


class RunnerConfig:
    def __init__(self, env: Optional[Dict[str, str]] = None):
        env = os.environ if env is None else env
        self.token = env.get("CODE_RUNNER_TOKEN") or ""
        self.allow_anonymous = env.get("CODE_RUNNER_ALLOW_ANONYMOUS", "") == "1"
        self.concurrency = int(env.get("CODE_RUNNER_CONCURRENCY") or 4)
        self.limits = Limits.from_env(env)
        self.max_body = self.limits.source_bytes + self.limits.input_bytes + 4096


def make_handler(config: RunnerConfig):
    gate = threading.BoundedSemaphore(config.concurrency)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"FoundryxCodeRunner/{RUNNER_VERSION}"

        def log_message(self, fmt, *args):  # quiet by default; no job content
            return

        def _send(self, status: int, body: Dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            if config.allow_anonymous and not config.token:
                return True
            if not config.token:
                return False
            header = self.headers.get("Authorization") or ""
            if not header.startswith("Bearer "):
                return False
            return hmac.compare_digest(header[7:].strip(), config.token)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True, "runnerVersion": RUNNER_VERSION})
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run":
                self._send(404, {"ok": False, "error": "not found"})
                return
            if not self._authorized():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > config.max_body:
                self._send(413, {"ok": False, "error": "payload too large"})
                return
            try:
                job = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"ok": False, "error": "invalid json"})
                return
            source = job.get("source")
            inputs = job.get("input") or {}
            if not isinstance(source, str) or not isinstance(inputs, dict):
                self._send(400, {"ok": False, "error": "source and input are required"})
                return
            with gate:
                result = execute(source, inputs, config.limits)
            self._send(200, result.to_dict())

    return Handler


def serve(host: str = "0.0.0.0", port: int = 8011, config: Optional[RunnerConfig] = None) -> None:
    config = config or RunnerConfig()
    if not config.token and not config.allow_anonymous:
        raise SystemExit("CODE_RUNNER_TOKEN is required (or CODE_RUNNER_ALLOW_ANONYMOUS=1 for local dev).")
    httpd = ThreadingHTTPServer((host, port), make_handler(config))
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
