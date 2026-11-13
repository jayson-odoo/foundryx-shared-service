"""Sorento ingest batch size: a configurable size under the vendor's hard ceiling.

Sorento production sits behind nginx with a 60s proxy timeout; a 1,000-record
purchase_order batch with per-record supplier back-create 504'd on prod
(2026-09-06). Sorento asked for a 200 default on document ingests and a
configurable size. ``SORENTO_MAX_BATCH`` (1000) stays the HARD CEILING -
Sorento rejects more per request - and a new ``settings.
autocount_sink_batch_size`` (env ``AUTOCOUNT_SINK_BATCH_SIZE``, default 200,
1..ceiling) is what every chunking loop actually uses: write, dry run, read
back and deletions alike. ``sorento_sink_from_connection`` reads the setting at
CALL time, the same "retune without a restart" contract as the sink timeout.

Transport-mock style mirrors ``tests/test_sorento_sink.py``.
"""
from __future__ import annotations

import json
from typing import Any, Callable, List

import httpx
import pytest

from modules.autocount.canonical.masters import CanonicalSupplier
from modules.autocount.sinks_sorento import (
    SORENTO_MAX_BATCH,
    SorentoSink,
    sorento_sink_from_connection,
)

ENV = "AUTOCOUNT_SINK_BATCH_SIZE"


def _supplier(i: int) -> CanonicalSupplier:
    return CanonicalSupplier(
        source_ref=f"AED_VSOFT:{i}", source_doc_no=f"C{i}", code=f"C{i}", name="JAPAN",
        email=None, is_active=True,
    )


class _Recorder:
    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return _respond(request)
        return httpx.MockTransport(handle)


def _respond(request: httpx.Request) -> httpx.Response:
    """One responder for every Sorento route the sink chunks over."""
    body = json.loads(request.content)
    path = request.url.path
    if "/read/" in path:
        return httpx.Response(200, json={"records": [], "not_found": list(body["source_refs"])})
    if path.endswith("/deletions"):
        refs = body["source_refs"]
        return httpx.Response(200, json={
            "summary": {"total": len(refs), "deleted": len(refs), "deactivated": 0,
                        "not_found": 0, "failed": 0, "retryable": 0},
            "records": [{"source_ref": r, "outcome": "deleted"} for r in refs],
        })
    records = [
        {"source_ref": r["source_ref"], "outcome": "created", "entity_id": f"id-{r['source_ref']}"}
        for r in body["records"]
    ]
    return httpx.Response(200, json={
        "summary": {"total": len(records), "created": len(records), "updated": 0,
                    "failed": 0, "retryable": 0},
        "records": records,
    })


def _sizes(rec: _Recorder, key: str) -> List[int]:
    return [len(json.loads(r.content)[key]) for r in rec.requests]


def _sink(rec: _Recorder, **kwargs: Any) -> SorentoSink:
    return SorentoSink(
        base_url="http://x", api_key="k", entity_type="supplier",
        transport=rec.transport(), **kwargs,
    )


def _force_setting(obj: Any, name: str, value: Any) -> Callable[[], None]:
    """Set an attribute on the live pydantic ``settings`` object bypassing
    field validation (the field may not exist yet on this HEAD); returns the
    restore callable."""
    had = name in obj.__dict__
    previous = obj.__dict__.get(name)
    object.__setattr__(obj, name, value)

    def _restore() -> None:
        if had:
            object.__setattr__(obj, name, previous)
        else:
            obj.__dict__.pop(name, None)

    return _restore


# ── (a) the setting: default 200, env override, bounds naming the ceiling ──


def test_batch_size_setting_defaults_to_200(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv(ENV, raising=False)
    assert Settings().autocount_sink_batch_size == 200


def test_batch_size_setting_is_overridable_from_the_environment(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv(ENV, "7")
    assert Settings().autocount_sink_batch_size == 7
    monkeypatch.setenv(ENV, str(SORENTO_MAX_BATCH))
    assert Settings().autocount_sink_batch_size == SORENTO_MAX_BATCH
    monkeypatch.setenv(ENV, "1")
    assert Settings().autocount_sink_batch_size == 1


@pytest.mark.parametrize("bad", ["0", str(SORENTO_MAX_BATCH + 1)], ids=["zero", "over-ceiling"])
def test_batch_size_setting_rejects_out_of_range_values_naming_the_ceiling(monkeypatch, bad):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv(ENV, bad)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert str(SORENTO_MAX_BATCH) in str(exc.value)


# ── (b) batch_size=3, 7 items -> 3 POSTs of 3/3/1 on every chunked route ──


def test_write_batch_chunks_at_the_configured_batch_size():
    rec = _Recorder()
    sink = _sink(rec, batch_size=3)
    results = sink.write_batch([_supplier(i) for i in range(7)], request_id="t")
    assert len(results) == 7 and all(r.delivered for r in results)
    assert _sizes(rec, "records") == [3, 3, 1]


def test_dry_run_chunks_at_the_configured_batch_size():
    rec = _Recorder()
    sink = _sink(rec, batch_size=3)
    result = sink.dry_run([_supplier(i) for i in range(7)])
    assert result.summary["total"] == 7
    assert len(result.predictions) == 7
    assert _sizes(rec, "records") == [3, 3, 1]


def test_read_back_chunks_at_the_configured_batch_size():
    rec = _Recorder()
    sink = _sink(rec, batch_size=3)
    refs = [f"AED_VSOFT:{i}" for i in range(7)]
    result = sink.read_back(refs)
    assert result["not_found"] == refs
    assert _sizes(rec, "source_refs") == [3, 3, 1]


def test_delete_batch_chunks_at_the_configured_batch_size():
    rec = _Recorder()
    sink = _sink(rec, batch_size=3)
    refs = [f"AED_VSOFT:{i}" for i in range(7)]
    result = sink.delete_batch(refs)
    assert result["summary"]["deleted"] == 7
    assert len(result["records"]) == 7
    assert _sizes(rec, "source_refs") == [3, 3, 1]


# ── (c) the vendor ceiling clamps any larger request ───────────────────────


def test_a_batch_size_above_the_ceiling_clamps_to_it():
    rec = _Recorder()
    sink = _sink(rec, batch_size=5000)
    assert sink.batch_size == SORENTO_MAX_BATCH

    sink.write_batch([_supplier(i) for i in range(SORENTO_MAX_BATCH)], request_id="t")
    assert _sizes(rec, "records") == [SORENTO_MAX_BATCH]

    rec.requests.clear()
    sink.write_batch([_supplier(i) for i in range(SORENTO_MAX_BATCH + 1)], request_id="t")
    assert _sizes(rec, "records") == [SORENTO_MAX_BATCH, 1]


def test_the_constructor_default_is_the_ceiling():
    """A sink built directly (tests, ad-hoc scripts) keeps today's behaviour;
    only the connection factory injects the operator's setting."""
    assert _sink(_Recorder()).batch_size == SORENTO_MAX_BATCH


# ── (d) the connection factory reads the LIVE setting at call time ────────


def test_the_factory_picks_up_the_live_batch_size_setting():
    from app.config import settings as live_settings

    restore = _force_setting(live_settings, "autocount_sink_batch_size", 7)
    try:
        sink = sorento_sink_from_connection(
            {"baseUrl": "http://x"}, {"apiKey": "k"},
            entity_type="supplier", company_code="C1",
        )
    finally:
        restore()
    assert sink.batch_size == 7
