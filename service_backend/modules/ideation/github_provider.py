"""GitHub connection provider (type ``scm``) for the BR "Send to build" hand-off.

One secret field, a fine-grained personal access token, Fernet-encrypted in
``connections.credentials_json`` and never echoed. ``test()`` runs the harmless
authenticated ``GET /user`` and names the failing step.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.integrations.base import TestResult

from .github_client import GITHUB_API

GITHUB_PROVIDER_KEY = "github"
GITHUB_CONNECTION_TYPE = "scm"


class GitHubProvider:
    provider = GITHUB_PROVIDER_KEY
    type = GITHUB_CONNECTION_TYPE
    title = "GitHub"
    description = (
        "Files build requests as issues in your product repositories. One token "
        "covers every repository it can see."
    )
    icon = "github"
    test_label = "Test connection"
    test_target = None

    def __init__(self, transport: Optional[httpx.BaseTransport] = None) -> None:
        self._transport = transport

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "token",
                "label": "Access token",
                "type": "password",
                "required": True,
                "secret": True,
            }
        ]

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
    ) -> TestResult:
        token = str(credentials.get("token", "")).strip()
        if not token:
            return TestResult(ok=False, message="Enter the GitHub access token.")
        try:
            with httpx.Client(timeout=15.0, transport=self._transport) as client:
                response = client.get(
                    f"{GITHUB_API}/user",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "Authorization": f"Bearer {token}",
                    },
                )
        except httpx.HTTPError:
            return TestResult(ok=False, message="GitHub is unreachable")
        if response.status_code in (401, 403):
            return TestResult(ok=False, message="GitHub rejected the token")
        if response.status_code != 200:
            return TestResult(
                ok=False, message=f"GitHub returned an error ({response.status_code})"
            )
        try:
            login = response.json().get("login") or "unknown"
        except ValueError:
            login = "unknown"
        return TestResult(ok=True, message=f"Connected to GitHub as {login}")
