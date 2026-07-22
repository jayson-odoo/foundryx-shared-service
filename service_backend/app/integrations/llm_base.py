"""Shared plumbing for the three `type='llm'` provider adapters (AC-BI-01/02).

**Why raw HTTP and not the vendor SDKs.** `anthropic`, `openai` and
`google-genai` are three heavyweight dependencies with their own transitive
trees and release cadences, for what is — in every case — a single JSON POST and
a single JSON GET. `httpx` is already a project dependency, so the adapters
speak the vendors' REST APIs directly. That keeps the dependency surface flat,
makes the `_is_dev` stub seam trivially importable, and means a live test needs
nothing but an API key. Per the `s3_provider` convention the transport import
still happens INSIDE the methods.

Each adapter owns its own structured-output mechanism (`LLMProvider`'s
contract): no caller ever branches on provider.
"""
from typing import Any, Dict, List, Optional

from app.integrations.base import LLMError, ModelOption, TestResult

# A provider call is a foreground, user-visible request (the grill turn is
# synchronous, Bi-D10) — long enough for a real completion, short enough that a
# hung vendor doesn't pin a worker forever.
LLM_TIMEOUT_SECONDS = 120.0
LLM_LIST_TIMEOUT_SECONDS = 20.0
# Bounded so a runaway model can't bill unboundedly on one turn.
DEFAULT_MAX_TOKENS = 4096


def _http_json(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float,
) -> Dict[str, Any]:
    """One JSON round-trip, with vendor errors normalised to ``LLMError``.

    The raised message NEVER contains the request headers (the API key lives
    there) — only the vendor's own error text, truncated (AC-BI-04).
    """
    import httpx  # noqa: PLC0415 — imported here so the stub seam works without it

    try:
        response = httpx.request(
            method, url, headers=headers, json=json_body, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 — any transport failure
        raise LLMError(f"Could not reach the provider ({type(exc).__name__}).") from exc

    if response.status_code >= 400:
        raise LLMError(_clean_error(response.status_code, response.text))
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError("The provider returned a non-JSON response.") from exc


def _clean_error(status_code: int, body: str) -> str:
    """A short, human-readable reason — never a raw traceback, never the key."""
    detail = (body or "").strip().replace("\n", " ")
    if len(detail) > 300:
        detail = detail[:300] + "…"
    if status_code in (401, 403):
        return "The API key was rejected by the provider."
    if status_code == 404:
        return f"The provider rejected the request as not found — {detail}"
    if status_code == 429:
        return "The provider rate-limited this request — try again shortly."
    return f"The provider returned HTTP {status_code} — {detail}"


def require_key(credentials: Dict[str, Any], key: str = "apiKey") -> str:
    value = str(credentials.get(key, "")).strip()
    if not value:
        raise LLMError("No API key is configured for this connection.")
    return value


class LLMProviderBase:
    """Shared identity + `fields()` + `test()` for the LLM catalog cards.

    ``test()`` DOUBLES as the model-list probe (AC-BI-04): listing models proves
    the key, needs no prompt and costs nothing.
    """

    type = "llm"
    test_label = "Verify key"
    test_target = None  # listing models needs no user input

    provider = ""  # subclasses
    # Curated fallback used when the live catalog call fails (AC-BI-05).
    static_models: List[ModelOption] = []

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "apiKey",
                "label": "API key",
                "type": "password",
                "required": True,
                "secret": True,
            }
        ]

    def models(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> List[ModelOption]:
        raise NotImplementedError

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        try:
            found = self.models(config, credentials)
        except LLMError as exc:
            return TestResult(ok=False, message=str(exc))
        if not found:
            return TestResult(
                ok=False, message="The key worked but the provider listed no usable chat models."
            )
        return TestResult(
            ok=True, message=f"Key verified — {len(found)} chat models available."
        )


def sorted_models(options: List[ModelOption]) -> List[ModelOption]:
    """Newest first (AC-BI-05); undated entries keep their catalog order last."""
    return sorted(options, key=lambda m: (m.created is None, -(m.created or 0)))
