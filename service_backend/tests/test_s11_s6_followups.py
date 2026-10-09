"""Sprint-5/11 S6 follow-ups (coordinator round after the S6 review-fix
round was approved) - ``http_source/client.py``: a closed ``HttpApiClient``
must never resurrect a transport.

Context: ``_run_concurrent_batch``'s own ``shutdown(wait=False,
cancel_futures=True)`` (SF-3, S6 review round 1) can leave an abandoned
worker thread still mid-``get()`` after the run's own ``HttpApiSource.
close()`` already ran (``sync.py`` closes the source the moment the run's
outcome is decided, without waiting for stragglers). Before this fix, that
straggler's ``self._client`` read would silently build a BRAND NEW
``httpx.Client`` and fire a real outbound request against a connection whose
run is already over.
"""
from __future__ import annotations

from typing import Any, List, Tuple

import httpx
import pytest

from modules.autocount.http_source.client import HttpApiClient, HttpTransportError

BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


def _mock_transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_after_close_raises_without_constructing_a_new_client(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"ItemCode": "X"}])

    client = HttpApiClient(BASE_URL, transport=_mock_transport(handler))
    # Sanity: works BEFORE close().
    client.get("/itembypage", {"page": 1, "pageSize": 1000})

    client.close()

    # Spy installed AFTER the initial (pre-close) construction above, so it
    # only ever sees a construction attempt made WHILE closed.
    construct_calls: List[Tuple[Any, Any]] = []
    real_client_cls = httpx.Client

    class _SpyClient(real_client_cls):  # noqa: D101 - test-local spy
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            construct_calls.append((args, kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _SpyClient)

    with pytest.raises(HttpTransportError):
        client.get("/itembypage", {"page": 2, "pageSize": 1000})

    assert construct_calls == [], (
        f"a closed HttpApiClient must never construct a new httpx.Client "
        f"(an abandoned worker would otherwise leak a real transport + fire "
        f"an outbound request after the run ended); got {construct_calls}"
    )


def test_closed_property_raises_even_when_never_lazily_initialized(monkeypatch):
    """The SAME guard applies when ``_client`` is read for the very FIRST
    time (never given a ``transport=`` at construction, and closed before
    any request was ever made) - the lazy-init branch itself must never
    run once closed."""
    construct_calls: List[Tuple[Any, Any]] = []
    real_client_cls = httpx.Client

    class _SpyClient(real_client_cls):  # noqa: D101 - test-local spy
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            construct_calls.append((args, kwargs))
            super().__init__(*args, **kwargs)

    client = HttpApiClient(BASE_URL)
    client.close()
    monkeypatch.setattr(httpx, "Client", _SpyClient)

    with pytest.raises(HttpTransportError):
        client.get("/itembypage", {"page": 1, "pageSize": 1000})

    assert construct_calls == [], (
        f"expected no httpx.Client() construction from a closed client that "
        f"was never lazily initialized either; got {construct_calls}"
    )
