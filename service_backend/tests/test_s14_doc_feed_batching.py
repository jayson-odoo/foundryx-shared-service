"""sprint-5/14 S0 - owner test "batching" (AC-14-20/21, T2).

Targets the `SorentoSink` EXTENSION plan section 3.4 describes directly
(book prop, `delete_doc_keys`, `RawVendorRecord`) rather than going through
the full `run_poll`/`run_sweep` pipeline - batching is a property of the
sink layer alone. `RawVendorRecord`/`delete_doc_keys`/the `book` constructor
kwarg do not exist yet (S0 red, D21): `AttributeError`/`TypeError` here are
the expected failure until the coder lands plan section 3.4.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.doc_feed.records import RawVendorRecord, source_ref
from modules.autocount.sinks_sorento import SorentoSink, sorento_sink_from_connection

from .s14_doc_feed_helpers import load_fixture

DO_FIXTURE = load_fixture("do-vendor-day.json")


def _raw_records(n: int, *, feed: str = "delivery_orders", book: str = "db1") -> List[RawVendorRecord]:
    out = []
    for i in range(n):
        doc_key = 100000 + i
        raw = {"DocKey": doc_key, "DocNo": f"DO-BATCH-{i}", "LastModified": "2026-09-29T09:00:00.000", "Details": []}
        out.append(RawVendorRecord(source_ref=f"{book}:DO:{doc_key}", entity_type=feed, raw=raw))
    return out


def _capturing_transport(chunk_sizes: List[int]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        records = payload.get("records") or payload.get("doc_keys") or []
        chunk_sizes.append(len(records))
        if "deletions" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dry_run": False,
                    "summary": {"total": len(records), "deactivated": len(records)},
                    "records": [
                        {"source_ref": f"db1:DO:{k}", "outcome": "deactivated", "entity_id": "x"}
                        for k in records
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "dry_run": False,
                "summary": {"total": len(records), "created": len(records)},
                "records": [
                    {"source_ref": r.get("source_ref", f"db1:DO:{r.get('DocKey')}"), "outcome": "created", "entity_id": "x"}
                    for r in records
                ],
            },
        )

    return httpx.MockTransport(handler)


def _order_capturing_transport(bodies: List[Dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        text = request.content.decode("utf-8")
        payload = json.loads(text)
        bodies.append(payload)
        return httpx.Response(
            200,
            json={"dry_run": False, "summary": {"total": 1, "created": 1},
                  "records": [{"source_ref": payload["records"][0].get("source_ref") or f"db1:DO:{payload['records'][0].get('DocKey')}", "outcome": "created", "entity_id": "x"}]},
        )

    return httpx.MockTransport(handler)


# ── ingest batching, cap 1000 (AC-14-21) ─────────────────────────────────────


def test_2500_records_at_the_setting_maximum_never_post_more_than_1000():
    chunk_sizes: List[int] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1", batch_size=5000,
        transport=_capturing_transport(chunk_sizes),
    )
    sink.write_batch(_raw_records(2500), request_id="req-2500")
    assert chunk_sizes, "no chunk POSTs were made"
    assert max(chunk_sizes) <= 1000
    assert sum(chunk_sizes) == 2500


def test_default_batch_size_is_200_via_the_connection_factory():
    chunk_sizes: List[int] = []
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://crm.example.test"}, {"apiKey": "k"},
        entity_type="delivery_orders", company_code="SRT",
        transport=_capturing_transport(chunk_sizes),
    )
    # book is only passed through by the doc-feed caller (D3) - a plain
    # `sorento_sink_from_connection` call with no `book` kwarg must still
    # build cleanly (byte-identical to every pre-plan-14 caller); this test
    # only pins the batch SIZE, so `sink.book` is left at its default.
    sink.write_batch(_raw_records(450), request_id="req-450")
    assert chunk_sizes == [200, 200, 50]


# ── deletions batching, cap 1000 doc_keys (AC-14-21) ─────────────────────────


def test_1500_deletion_keys_chunk_at_1000():
    chunk_sizes: List[int] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1", batch_size=1000,
        transport=_capturing_transport(chunk_sizes),
    )
    keys = list(range(500000, 501500))
    sink.delete_doc_keys(keys, doc_date_from="2026-08-15", doc_date_to="2026-09-28", dry_run=False)
    assert chunk_sizes == [1000, 500]


# ── body key order: companyCode, book, records (D3, 13.2) ──────────────────


def test_ingest_body_order_is_companyCode_then_book_then_records():
    bodies: List[Dict[str, Any]] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1",
        transport=_order_capturing_transport(bodies),
    )
    sink.write_batch(_raw_records(1), request_id="req-order")
    assert list(bodies[0].keys())[:3] == ["companyCode", "book", "records"]


def test_deletions_body_order_is_companyCode_book_doc_date_from_doc_date_to_doc_keys():
    bodies: List[Dict[str, Any]] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1",
        transport=_order_capturing_transport(bodies),
    )
    sink.delete_doc_keys([1], doc_date_from="2026-08-15", doc_date_to="2026-09-28", dry_run=False)
    assert list(bodies[0].keys()) == [
        "companyCode", "book", "doc_date_from", "doc_date_to", "doc_keys",
    ]


def test_body_omits_book_when_none_unchanged_from_before():
    """D3: "unchanged when None" - a sink built with no `book` (every
    existing pre-plan-14 caller) must keep posting the SAME two-key body it
    always has."""
    bodies: List[Dict[str, Any]] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT",
        transport=_order_capturing_transport(bodies),
    )
    sink.write_batch(_raw_records(1), request_id="req-no-book")
    assert "book" not in bodies[0]
    assert list(bodies[0].keys()) == ["companyCode", "records"]


# ── fixture JSON equality: Details + unknown key survive verbatim (AC-14-20, D18) ─


def test_pushed_record_is_json_equal_to_the_vendor_record_incl_details_and_unknown_key():
    header = dict(DO_FIXTURE[0])
    header["AnUnknownFutureVendorField"] = "kept-verbatim"
    ref = source_ref("delivery_orders", "db1", header)
    record = RawVendorRecord(source_ref=ref, entity_type="delivery_orders", raw=header)

    bodies: List[Dict[str, Any]] = []
    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1",
        transport=_order_capturing_transport(bodies),
    )
    sink.write_batch([record], request_id="req-fixture")

    posted = bodies[0]["records"][0]
    assert posted == header
    assert posted["Details"] == header["Details"]
    assert posted["AnUnknownFutureVendorField"] == "kept-verbatim"


def test_push_order_is_last_modified_ascending_across_the_two_fixture_records():
    records = [
        RawVendorRecord(
            source_ref=source_ref("delivery_orders", "db1", r), entity_type="delivery_orders", raw=r
        )
        for r in reversed(DO_FIXTURE)  # deliberately fed newest-first
    ]
    from modules.autocount.doc_feed.records import push_order

    ordered = push_order([r.raw for r in records])
    assert [r["DocKey"] for r in ordered] == [55120, 55121]
