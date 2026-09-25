"""Plan 13 S0 - Group A payload/verdict parity against the S0 fixtures
(`documentation/plans/sprint-5/13-fixtures/`, Appendix A7). RED before the
coder.

Every test that constructs a ``SorentoSink(entity_type=ENTITY_STOCK_BALANCE,
...)`` fails IMMEDIATELY with ``SorentoSinkError`` ("No Sorento ingest path
...") until AC-13-01 lands (`sinks_sorento._ENTITY_PATH` has no
``stock_balance`` entry today) - that single missing map entry is the ONE
reason every test in this file is red; nothing here is a broken test.

Pins: AC-13-03, AC-13-04, AC-13-05.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.canonical.masters import CanonicalStockBalance, ENTITY_STOCK_BALANCE
from modules.autocount.sinks_sorento import SorentoSink, SorentoSinkError

FIXTURES = Path(__file__).resolve().parents[2] / "documentation" / "plans" / "sprint-5" / "13-fixtures"


def _load(name: str) -> Dict[str, Any]:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _records_from_fixture() -> List[CanonicalStockBalance]:
    request = _load("stock_balances-ingest-request.json")
    return [CanonicalStockBalance(**row) for row in request["records"]]


def _sink(handler, **kwargs) -> SorentoSink:
    return SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_STOCK_BALANCE,
        transport=httpx.MockTransport(handler), company_code="SRT", **kwargs,
    )


# ── AC-13-03: request payload byte-for-byte parity ──────────────────────────


def test_to_records_matches_the_fixture_request_rows_exactly():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unused
        return httpx.Response(200, json={"summary": {}, "records": []})

    sink = _sink(handler)
    records = _records_from_fixture()
    projected = sink._to_records(records)
    expected = _load("stock_balances-ingest-request.json")["records"]
    assert json.dumps(projected, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_qty_is_always_a_json_integer_never_a_string_or_float():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unused
        return httpx.Response(200, json={"summary": {}, "records": []})

    sink = _sink(handler)
    projected = sink._to_records(_records_from_fixture())
    for row in projected:
        assert isinstance(row["qty"], int), row


def test_write_batch_posts_the_body_the_fixture_describes():
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        response = _load("stock_balances-ingest-response.json")
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    records = _records_from_fixture()
    sink.write_batch(records, request_id="req-1")
    assert len(calls) == 1
    assert calls[0].url.path.endswith("/ingest/stock_balances")
    sent = json.loads(calls[0].content)
    assert sent["companyCode"] == "SRT"
    expected = _load("stock_balances-ingest-request.json")["records"]
    assert json.dumps(sent["records"], sort_keys=True) == json.dumps(expected, sort_keys=True)


# ── AC-13-04: response verdicts, dependent-entity tolerance, warnings ──────


def test_write_batch_results_carry_warnings_and_delivered_flag():
    response = _load("stock_balances-ingest-response.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    records = _records_from_fixture()
    results = sink.write_batch(records, request_id="req-1")
    by_ref = {r.source_ref: result for r, result in zip(records, results)}

    inactive_ref = response["records"][4]["source_ref"]  # CON, warehouse_inactive
    unresolved_ref = response["records"][5]["source_ref"]  # BRW-VAR, warehouse_unresolved
    retryable_ref = response["records"][8]["source_ref"]  # item Sorento lacks

    assert by_ref[inactive_ref].ok is True
    assert by_ref[inactive_ref].delivered is True
    assert "warehouse_inactive" in by_ref[inactive_ref].warnings

    assert by_ref[unresolved_ref].ok is True
    assert "warehouse_unresolved" in by_ref[unresolved_ref].warnings

    assert by_ref[retryable_ref].ok is False
    assert by_ref[retryable_ref].outcome == "retryable"


def test_retryable_stock_message_names_the_product_not_category_or_uom():
    """AC-13-04 - stock joins ``_DEPENDENT_ENTITIES``; its retryable message
    is entity-specific ("its product has not synced yet"), never the
    product entity's own "category or unit of measure" sentence."""
    response = _load("stock_balances-ingest-response.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    records = _records_from_fixture()
    results = sink.write_batch(records, request_id="req-1")
    retryable = next(r for r in results if r.outcome == "retryable")
    assert "its product has not synced yet" in retryable.message, retryable.message
    assert "category or unit of measure" not in retryable.message


def test_a_failed_verdict_quarantines_never_retries():
    """Control: a genuine ``failed`` verdict (bad data) is NOT the
    dependent-entity tolerance - it must read exactly like every other
    master's ``failed`` (D13's rule), never silently downgraded."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "summary": {"total": 1, "failed": 1},
                "records": [{"source_ref": "AED_SORENTO:BAD|MBS", "outcome": "failed", "errors": {"qty": "negative"}}],
            },
        )

    sink = _sink(handler)
    rec = CanonicalStockBalance(
        source_ref="AED_SORENTO:BAD|MBS", item_code="BAD", location_code="MBS", qty=0,
    )
    results = sink.write_batch([rec], request_id="req-1")
    assert results[0].ok is False
    assert results[0].outcome == "failed"


# ── AC-13-05: deletions carry ``pairs``, guarded, chunk-restricted ─────────


def _pairs_from_fixture() -> Dict[str, Dict[str, str]]:
    return _load("stock_balances-deletions-request.json")["pairs"]


def test_delete_batch_posts_pairs_restricted_to_the_chunk():
    calls: List[httpx.Request] = []
    fixture = _load("stock_balances-deletions-request.json")
    response = _load("stock_balances-deletions-response.json")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    sink.delete_batch(fixture["source_refs"], pairs=_pairs_from_fixture())
    assert len(calls) == 1
    sent = json.loads(calls[0].content)
    assert sent["source_refs"] == fixture["source_refs"]
    assert sent["pairs"] == fixture["pairs"]


def test_delete_batch_omits_a_ref_with_no_pairs_entry():
    """The 4th fixture ref (``GHOST-ITEM|MWH``) deliberately has no ``pairs``
    entry - the sent body's ``pairs`` map must not invent one for it."""
    calls: List[httpx.Request] = []
    fixture = _load("stock_balances-deletions-request.json")
    response = _load("stock_balances-deletions-response.json")
    ghost_ref = fixture["source_refs"][3]
    assert ghost_ref not in fixture["pairs"], "fixture precondition"

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    sink.delete_batch(fixture["source_refs"], pairs=_pairs_from_fixture())
    sent = json.loads(calls[0].content)
    assert ghost_ref not in sent.get("pairs", {})


def test_delete_batch_multi_key_response_verdicts_parsed():
    fixture = _load("stock_balances-deletions-request.json")
    response = _load("stock_balances-deletions-response.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    result = sink.delete_batch(fixture["source_refs"], pairs=_pairs_from_fixture())
    outcomes = {r["source_ref"]: r["outcome"] for r in result["records"]}
    assert outcomes[fixture["source_refs"][0]] == "deleted"
    assert outcomes[fixture["source_refs"][1]] == "not_found"


def test_write_batch_entity_id_always_present_null_only_on_warning_or_retryable():
    """Sorento's 2026-09-25 review correction 1: `entity_id` is ALWAYS a key
    on the verdict, never omitted - `null` exactly on a warning/retryable/
    failed row, a real id otherwise. Never assert a SPECIFIC id/format."""
    response = _load("stock_balances-ingest-response.json")
    for record in response["records"]:
        assert "entity_id" in record, record
        if record["outcome"] in ("retryable", "failed") or record.get("warnings"):
            assert record["entity_id"] is None, record
        else:
            assert record["entity_id"] is not None, record


def test_dry_run_diff_rules_created_none_updated_empty_or_populated():
    """Sorento's correction 2/3: `created` carries no `diff` key at all;
    `updated` with no change carries `diff: {}`; `updated` with a genuine
    change carries `diff.qty.{current,incoming}`; `diff` is dry-run only."""
    dry = _load("stock_balances-ingest-dry-run-response.json")
    real = _load("stock_balances-ingest-response.json")
    for record in real["records"]:
        assert "diff" not in record, "the real-run response must never carry diff"
    for record in dry["records"]:
        if record["outcome"] == "created":
            assert "diff" not in record, record
        elif record["outcome"] == "updated":
            assert "diff" in record, record
            if record["diff"]:
                assert set(record["diff"]) == {"qty"}
                assert set(record["diff"]["qty"]) == {"current", "incoming"}


def test_gateway_summaries_carry_no_extra_keys():
    """Sorento's correction 4: the WIRE summary shapes are narrower than
    Foundryx's own synthesized run summary - never conflate the two."""
    ingest = _load("stock_balances-ingest-response.json")
    assert set(ingest["summary"]) == {"total", "created", "updated", "failed", "retryable"}
    deletions = _load("stock_balances-deletions-response.json")
    assert set(deletions["summary"]) == {"total", "deleted", "deactivated", "not_found", "failed"}


def test_delete_batch_body_level_malformed_pairs_is_a_batch_422():
    """Sorento's correction 5 (body-level): `pairs` malformed as a WHOLE
    (not an object / over the cap) is one 422 for the entire batch, never a
    per-record outcome - the sink must raise, not return per-ref verdicts."""
    error = _load("stock_balances-deletions-error-422-invalid-body.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json=error)

    sink = _sink(handler)
    with pytest.raises(SorentoSinkError):
        sink.delete_batch(["AED_SORENTO:X|MBS"], pairs={"bad": "shape"})


def test_delete_batch_single_malformed_pairs_entry_fails_only_that_ref():
    """Sorento's correction 5 (per-entry): one malformed `pairs` entry
    resolves `failed` for JUST that ref; a clean ref in the SAME batch still
    deletes."""
    request = _load("stock_balances-deletions-malformed-entry-request.json")
    response = _load("stock_balances-deletions-malformed-entry-response.json")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    result = sink.delete_batch(request["source_refs"], pairs=request["pairs"])
    outcomes = {r["source_ref"]: r["outcome"] for r in result["records"]}
    assert outcomes[request["source_refs"][0]] == "deleted"
    assert outcomes[request["source_refs"][1]] == "failed"


def test_write_batch_duplicate_pair_in_one_batch_last_value_wins():
    """Sorento's correction 6: the SAME (item_code, location_code) pair
    submitted twice in one batch is processed in order, last value wins -
    first `created`, second `updated`, both echoing the same `entity_id`."""
    request = _load("stock_balances-ingest-duplicate-pair-request.json")
    response = _load("stock_balances-ingest-duplicate-pair-response.json")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"summary": response["summary"], "records": response["records"]})

    sink = _sink(handler)
    records = [CanonicalStockBalance(**row) for row in request["records"]]
    results = sink.write_batch(records, request_id="req-1")
    assert [r.outcome for r in results] == ["created", "updated"]
    assert results[0].external_id == results[1].external_id


def test_delete_batch_pairs_kwarg_omitted_for_a_non_pair_keyed_task():
    """AC-13-05's guard: ``pairs`` is only ever honoured for stock's own
    (item_code, location_code) key shape - this sink call with NO ``pairs``
    kwarg at all must keep sending exactly today's body shape (no ``pairs``
    key at all), a byte-identical control for every other entity's deletes."""
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"summary": {}, "records": []})

    sink = _sink(handler)
    sink.delete_batch(["AED_SORENTO:X|MBS"])
    sent = json.loads(calls[0].content)
    assert "pairs" not in sent
