"""Sprint-5/10 S6 - AC-10-85's own last sentence: "Lookup endpoints obey the
same page size, timeout and retry as the main path."

Kept OUT of ``test_s10_s6_connection_sizing.py`` on purpose: that file is the
tester's red file for this round and stays byte-identical apart from one
additive fixture argument (``_config(..., lookups=...)``, whose default
reproduces the previous empty list exactly). The shared fixtures are imported
from it rather than copied, so there is one definition of "an open connection
with these settings" for the whole round - including its autouse
``_block_live_network`` guard, which pytest collects from THIS module's
namespace once imported.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.sources import Watermark
from tests.test_s10_s6_connection_sizing import (  # noqa: F401 - `_block_live_network` is an autouse fixture, collected by import
    _block_live_network,
    _company,
    _config,
    _ctx,
    _ok_page,
    _open_connection,
    _transport,
)

ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


def test_lookup_walk_uses_the_same_connection_page_size_and_timeout(session_factory):
    """The lookup path (``/itemuombypage``) is walked through the SAME
    ``_walk_endpoint``/``self._client`` the main path uses (AC-10-02's "the
    SAME page walker") - so it must request the connection's OWN pageSize
    (222) and be built against the connection's OWN requestTimeoutSeconds
    (33), never the module defaults, exactly like the main path."""
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.http_source.source import HttpApiSource

    db = session_factory()
    try:
        conn = _open_connection(db, page_size="222", timeout_seconds="33")
        company = _company(db, conn.id)
        config = _config(db, company, conn.id, lookups=[ITEM_UOM_LOOKUP])

        calls: List[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/itemuombypage"):
                return httpx.Response(200, json=_ok_page([{"ItemCode": "A1", "Price": 9.5}]))
            return httpx.Response(200, json=_ok_page([{"ItemCode": "A1"}]))

        captured_kwargs: Dict[str, Any] = {}

        def spy_factory(base_url, **kwargs):
            captured_kwargs.update(kwargs)
            return HttpApiClient(base_url, transport=_transport(handler))

        import modules.autocount.http_source.source as source_module

        original = source_module.HttpApiClient
        source_module.HttpApiClient = spy_factory
        try:
            source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
            source.fetch_changes(Watermark())
        finally:
            source_module.HttpApiClient = original

        lookup_calls = [c for c in calls if c.url.path.endswith("/itemuombypage")]
        assert lookup_calls, "the lookup endpoint was never called"
        assert lookup_calls[0].url.params.get("pageSize") == "222", (
            f"expected the lookup's FIRST request to ask for the connection's "
            f"own pageSize (222), got {lookup_calls[0].url.params.get('pageSize')!r}"
        )
        # ONE `HttpApiClient` backs both the main walk and every lookup (the
        # constructor is called once, in `HttpApiSource.__init__`) - so its
        # own `timeout_seconds` is already the connection's value.
        assert captured_kwargs.get("timeout_seconds") == 33.0, (
            f"the shared client was not built with the connection's own "
            f"requestTimeoutSeconds (33); captured: {captured_kwargs!r}"
        )
    finally:
        db.close()
