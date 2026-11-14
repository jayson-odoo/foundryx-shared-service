"""Outbound HTTP to the product - every request carries a fresh signed call JWT.

``TRANSPORT`` is the test seam: None = real httpx; tests set an
``httpx.MockTransport``. Raises ``httpx.HTTPError`` on transport failure.
"""

from __future__ import annotations
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.services.url_guard import GuardedTransport, UrlGuardError, assert_deliverable

from .. import crypto, registry
from ..registry import Product

TRANSPORT: Optional[httpx.BaseTransport] = None
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def send(product: Product, *, method: str, raw_path: str, query: str, body: bytes, sub: str,
         grant_id: str, consented_at: int, tool: str,
         timeout_seconds: Optional[int] = None) -> httpx.Response:
    token = crypto.sign_call(
        product.ss_to_product_secret, connection_id=product.connection_id,
        audience=product.call_audience, sub=sub, grant_id=grant_id, consented_at=consented_at,
        tool=tool, method=method, raw_path=raw_path, query=query, body=body)
    url = product.api_base_url + raw_path + (f"?{query}" if query else "")
    if urlsplit(url).hostname != urlsplit(product.api_base_url).hostname:
        raise httpx.TransportError("host mismatch")  # nothing is sent
    if product.guard_outbound:  # tenant-set base URL: re-check right before sending
        try:
            assert_deliverable(url, subject="API base URL")
        except UrlGuardError:
            raise httpx.TransportError("blocked target") from None  # nothing is sent
    headers = {"Authorization": f"Connector {token}", "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(float(timeout_seconds or registry.call_timeout_seconds()))
    transport = TRANSPORT
    if transport is None and product.guard_outbound:
        transport = GuardedTransport(subject="API base URL")
    try:
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
            with client.stream(method.upper(), url, content=body or None, headers=headers) as resp:
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise httpx.TransportError("response too large")
                    chunks.append(chunk)
    except UrlGuardError:
        raise httpx.TransportError("blocked target") from None  # nothing is sent
    kept = [(k, v) for k, v in resp.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
    return httpx.Response(resp.status_code, headers=kept, content=b"".join(chunks),
                          request=resp.request)
