"""macOS login-keychain reads. A secret is returned to the caller and goes
nowhere else: never logged, printed, put in an exception message or written to
a file."""

from __future__ import annotations

import subprocess

HF_ACCOUNT = "planner3d"
HF_SERVICE = "huggingface-read-token"
WORKER_TOKEN_ACCOUNT = "planner3d"
WORKER_TOKEN_SERVICE = "planner3d-worker-token"


class KeychainError(Exception):
    pass


def read_secret(account: str, service: str) -> str:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeychainError(f"keychain unavailable for service {service}") from exc
    value = proc.stdout.strip()
    if proc.returncode != 0 or not value:
        raise KeychainError(f"no keychain item for service {service}")
    return value


def hugging_face_token() -> str:
    return read_secret(HF_ACCOUNT, HF_SERVICE)


def worker_token() -> str:
    return read_secret(WORKER_TOKEN_ACCOUNT, WORKER_TOKEN_SERVICE)
