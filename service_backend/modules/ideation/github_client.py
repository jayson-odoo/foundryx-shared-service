"""Thin GitHub REST wrapper for the BR "Send to build" hand-off.

Sync httpx (15s timeout). Every failure raises :class:`GitHubError` carrying the
failing ``step`` and the HTTP ``status_code`` (``None`` for a transport error) so
the service can map it to a precise 502 message. The token is only ever put in
the ``Authorization`` header - never logged, never in an exception message.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .schemas import BUILD_REPO_PATTERN

GITHUB_API = "https://api.github.com"
GITHUB_TIMEOUT_SECONDS = 10
_TIMEOUT = float(GITHUB_TIMEOUT_SECONDS)


class GitHubError(Exception):
    def __init__(self, step: str, status_code: Optional[int] = None) -> None:
        self.step = step
        self.status_code = status_code
        detail = f"HTTP {status_code}" if status_code is not None else "unreachable"
        super().__init__(f"GitHub {step} failed ({detail})")


class GitHubClient:
    def __init__(
        self, token: str, *, transport: Optional[httpx.BaseTransport] = None
    ) -> None:
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        }
        self._transport = transport

    @staticmethod
    def _repo_path(repo: str) -> str:
        """``owner/name`` re-validated against the stored-repo shape (a row saved
        before the pattern existed must never reach the wire) and percent-encoded
        per segment. Raises ``ValueError`` before any request."""
        if not re.fullmatch(BUILD_REPO_PATTERN, repo or ""):
            raise ValueError("Invalid repository name.")
        return "/".join(quote(seg, safe="") for seg in repo.split("/"))

    def _request(
        self,
        step: str,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        ok: tuple = (200, 201),
    ) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=GITHUB_API,
                timeout=_TIMEOUT,
                headers=self._headers,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise GitHubError(step) from exc
        if response.status_code not in ok:
            raise GitHubError(step, response.status_code)
        return response

    def get_repo(self, repo: str) -> Dict[str, Any]:
        """The repository record (``private`` decides whether tenant text may be
        posted into it)."""
        data = self._request("repository lookup", "GET", f"/repos/{self._repo_path(repo)}").json()
        return {"private": data.get("private")}

    def ensure_label(self, repo: str, name: str, color: str) -> None:
        """GET the label; create it on 404 (colour without a leading ``#``)."""
        try:
            self._request("label lookup", "GET", f"/repos/{self._repo_path(repo)}/labels/{name}")
            return
        except GitHubError as exc:
            if exc.status_code != 404:
                raise
        self._request(
            "label create",
            "POST",
            f"/repos/{self._repo_path(repo)}/labels",
            json={"name": name, "color": color},
        )

    def create_issue(
        self, repo: str, title: str, body: str, labels: List[str]
    ) -> Dict[str, Any]:
        data = self._request(
            "issue create",
            "POST",
            f"/repos/{self._repo_path(repo)}/issues",
            json={"title": title, "body": body, "labels": labels},
        ).json()
        return {
            "number": data["number"],
            "html_url": data["html_url"],
            "node_id": data.get("node_id"),
        }

    def create_comment(self, repo: str, number: int, body: str) -> None:
        self._request(
            "issue comment",
            "POST",
            f"/repos/{self._repo_path(repo)}/issues/{number}/comments",
            json={"body": body},
        )

    def list_labelled_issues(
        self, repo: str, label: str, *, max_pages: int = 5
    ) -> List[Dict[str, Any]]:
        """Issues carrying ``label`` (any state), following ``Link: rel="next"``
        up to ``max_pages``. Body and label names are returned so the caller can
        verify a hit strictly. Pull requests are skipped."""
        out: List[Dict[str, Any]] = []
        path = f"/repos/{self._repo_path(repo)}/issues"
        params: Optional[Dict[str, str]] = {"labels": label, "state": "all", "per_page": "100"}
        for _ in range(max_pages):
            response = self._request("issue list", "GET", path, params=params)
            for hit in response.json() or []:
                if hit.get("pull_request"):
                    continue
                out.append(
                    {
                        "number": hit["number"],
                        "html_url": hit["html_url"],
                        "node_id": hit.get("node_id"),
                        "body": hit.get("body") or "",
                        "labels": [
                            (lab.get("name") if isinstance(lab, dict) else str(lab))
                            for lab in (hit.get("labels") or [])
                        ],
                    }
                )
            next_url = (response.links.get("next") or {}).get("url")
            # Only ever follow a next link on GitHub's own API host.
            if not next_url or not next_url.startswith(GITHUB_API + "/"):
                break
            path, params = next_url, None
        return out
