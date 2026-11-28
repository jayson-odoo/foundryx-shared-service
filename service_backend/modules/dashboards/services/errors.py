"""One error type for the whole module: rendered as the contract's flat body
``{"error", "message", ...}`` by ``gateway_auth.DashRoute`` (contract 3.8)."""
from __future__ import annotations

from typing import Any, Dict, Optional


class DashError(Exception):
    def __init__(self, status_code: int, code: str, message: str, extra: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}
        self.headers = headers or {}

    def body(self) -> Dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}


def not_found() -> DashError:
    return DashError(404, "not_found", "That dashboard was not found.")


def not_owner() -> DashError:
    return DashError(403, "not_owner", "Only the owner of a dashboard can change it.")


def spec_invalid(problems, message: str = "The dashboard is not valid.") -> DashError:
    return DashError(422, "spec_invalid", message, {"problems": list(problems)})
