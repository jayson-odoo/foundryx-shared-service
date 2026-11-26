"""Client for the CRM connector feed (sorento-crm #2801, contract frozen).

Base ``<crm>/api/v1/external/connector/v1``; every route is a GET with
``X-API-Key`` (the CRM connector integration key, whose user needs the
explicit ``integration.connector.read`` grant) and ``?company=<code>``.
Shapes are ``{"data": ...}``; codes only; unknown = null.

The connection is a core ``connections`` row (provider ``crm_connector_feed``,
type ``hub_source``), configured on the standard Settings -> Integrations
screen, key Fernet-encrypted and write-only (``HubSourceProvider``).

Outside development every request goes through the core guarded transport:
an admin-typed base URL must never reach an internal address.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.config import settings
from app.database import release_read_transactions
from app.integrations.base import TestResult
from app.services.url_guard import GuardedTransport

logger = logging.getLogger(__name__)

PROVIDER_KEY = "crm_connector_feed"
CONNECTION_TYPE = "hub_source"
FEED_PATH = "/api/v1/external/connector/v1"
CODES_PER_CALL = 200  # /availability cap (422 above)
PAGE_LIMIT = 200  # /products limit 1..200
TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # one feed answer
MAX_PAGES = 500  # 100k products
RUN_DEADLINE_SECONDS = 600.0  # one sync run, every call included


class FeedError(Exception):
    """A plain-words reason the feed could not be read (never a key or URL)."""

    def __init__(self, message: str, *, retry_after: Optional[int] = None, status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.status = status


@dataclass(frozen=True)
class FeedConfig:
    base_url: str
    company: str
    api_key: str


def _transport() -> Optional[httpx.BaseTransport]:
    if settings.environment == "development":
        return None
    return GuardedTransport(subject="The CRM address")


def _http() -> httpx.Client:
    """Module-level so tests can hand in a MockTransport-backed client."""
    return httpx.Client(timeout=TIMEOUT_SECONDS, transport=_transport())


def _explain(status: int, body: Dict[str, Any]) -> str:
    if status == 401:
        return "The CRM refused the key, or the integration is switched off."
    if status == 403:
        return "The CRM key's user lacks the connector read grant or this company."
    if status == 429:
        return "The CRM rate limit was reached."
    if status == 422:
        detail = body.get("detail")
        message = detail.get("message") if isinstance(detail, dict) else None
        if isinstance(message, str) and message.strip():
            clean = "".join(ch for ch in message if ch.isprintable())[:200]
            return f"The CRM refused the request: {clean}"
        return "The CRM refused the request."
    if status >= 500:
        return f"The CRM answered with an internal error ({status})."
    return f"The CRM answered {status}."


class FeedClient:
    def __init__(self, cfg: FeedConfig, client: Optional[httpx.Client] = None):
        self.cfg = cfg
        self._client = client
        self._deadline = time.monotonic() + RUN_DEADLINE_SECONDS

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if time.monotonic() > self._deadline:
            raise FeedError("The CRM took too long to answer this sync.")
        url = f"{self.cfg.base_url.rstrip('/')}{FEED_PATH}{path}"
        query = {"company": self.cfg.company, **{k: v for k, v in params.items() if v is not None}}
        release_read_transactions()
        client = self._client or _http()
        try:
            with client.stream(
                "GET", url, params=query, headers={"X-API-Key": self.cfg.api_key, "Accept": "application/json"}
            ) as response:
                status, retry = response.status_code, response.headers.get("Retry-After")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise FeedError("The CRM answer was too large.")
                    if time.monotonic() > self._deadline:
                        raise FeedError("The CRM took too long to answer this sync.")
        except httpx.HTTPError as exc:
            raise FeedError("Could not reach the CRM.") from exc
        finally:
            if self._client is None:
                client.close()
        try:
            body = json.loads(bytes(raw)) if raw else {}
        except ValueError:
            body = {}
        if status != 200:
            raise FeedError(
                _explain(status, body if isinstance(body, dict) else {}),
                retry_after=int(retry) if retry and retry.isdigit() else None,
                status=status,
            )
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise FeedError("The CRM answered in an unexpected shape.")
        return body

    def locations(self) -> List[Dict[str, Any]]:
        return self._get("/locations", {})["data"]

    def brands(self) -> List[Dict[str, Any]]:
        return self._get("/brands", {})["data"]

    def products(self) -> List[Dict[str, Any]]:
        """Every product the feed offers, paged by ``limit``/``offset``. A page
        larger than asked for, or more than ``MAX_PAGES`` pages, is refused."""
        rows: List[Dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            body = self._get("/products", {"limit": PAGE_LIMIT, "offset": offset})
            page = body["data"]
            if len(page) > PAGE_LIMIT:
                raise FeedError("The CRM sent more products than asked for.")
            rows.extend(page)
            total = body.get("total")
            offset += len(page)
            if not page or len(page) < PAGE_LIMIT or (isinstance(total, int) and offset >= total):
                return rows
        raise FeedError("The CRM lists more products than one sync can read.")

    def availability(self, codes: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """``code -> row`` for the given codes (chunks of 200); a code in
        ``missing`` is simply absent from the result."""
        out: Dict[str, Dict[str, Any]] = {}
        codes = list(codes)
        for start in range(0, len(codes), CODES_PER_CALL):
            chunk = codes[start: start + CODES_PER_CALL]
            body = self._get("/availability", {"codes": ",".join(chunk)})
            for row in body["data"]:
                if isinstance(row, dict) and isinstance(row.get("code"), str):
                    out[row["code"]] = row
        return out


def config_from(config: Dict[str, Any], credentials: Dict[str, Any]) -> FeedConfig:
    base_url = str(config.get("baseUrl") or "").strip()
    company = str(config.get("company") or "").strip()
    api_key = str(credentials.get("apiKey") or "").strip()
    allowed = ("https://", "http://") if settings.environment == "development" else ("https://",)
    if not base_url.lower().startswith(allowed):
        raise FeedError("Enter the CRM address (https://...).")
    if not company or len(company) > 50:
        raise FeedError("Enter the CRM company code.")
    if not api_key:
        raise FeedError("Enter the CRM connector key.")
    return FeedConfig(base_url=base_url, company=company, api_key=api_key)


class HubSourceProvider:
    """Settings -> Integrations card for the CRM stock feed (one per tenant:
    core's one-active-connection-per-type index)."""

    provider = PROVIDER_KEY
    type = CONNECTION_TYPE
    title = "CRM stock feed"
    description = "Read locations, brands, products and stock from the CRM for Hub Connector."
    icon = "share-2"
    test_label = "Test connection"
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "baseUrl", "label": "CRM address", "type": "text", "required": True,
             "placeholder": "https://crm.example.com"},
            {"key": "company", "label": "Company code", "type": "text", "required": True},
            {"key": "apiKey", "label": "Connector key", "type": "password", "required": True, "secret": True},
        ]

    def test(self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None) -> TestResult:
        try:
            cfg = config_from(config, credentials)
            count = len(FeedClient(cfg).locations())
        except FeedError as exc:
            return TestResult(ok=False, message=exc.message)
        return TestResult(ok=True, message=f"Connected. The CRM lists {count} locations for this company.")
