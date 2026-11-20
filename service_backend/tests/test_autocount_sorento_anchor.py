"""``SorentoSink`` against the AS-BUILT Sorento contract (plan 22 Appendix
A6/A7/A8).

Everything here is a CROSS-REPO contract detail. Sorento's own suite proves its
side; these prove ours reads and writes exactly what was agreed, so a drift on
either side fails loudly here instead of silently mis-delivering a customer's
master data.

No socket: an ``httpx.MockTransport`` answers each call and records the body.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.canonical.masters import CanonicalCustomer, ENTITY_CUSTOMER
from modules.autocount.sinks_sorento import (
    ANCHOR_ERROR_CODES,
    COMPANY_ANCHOR_AMBIGUOUS,
    COMPANY_ANCHOR_REQUIRED,
    COMPANY_BINDING_INVALID,
    SORENTO_MAX_BATCH,
    UNKNOWN_COMPANY,
    SinkAnchorError,
    SorentoSink,
    SorentoSinkError,
    sorento_sink_from_connection,
)

CODE = "SRT"


class Recorder:
    """Answers every call from a scripted responder and keeps the requests."""

    def __init__(self, responder):
        self.requests: List[Dict[str, Any]] = []
        self._responder = responder

    @property
    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            import json

            self.requests.append(
                {
                    "url": str(request.url),
                    "path": request.url.path,
                    "params": dict(request.url.params),
                    "json": json.loads(request.content or b"{}"),
                }
            )
            return self._responder(request, len(self.requests))

        return httpx.MockTransport(handle)


def _sink(responder, *, company_code: str | None = CODE) -> tuple[SorentoSink, Recorder]:
    rec = Recorder(responder)
    return (
        SorentoSink(
            base_url="https://sorento.example.com",
            api_key="key-1",
            entity_type=ENTITY_CUSTOMER,
            company_code=company_code,
            transport=rec.transport,
        ),
        rec,
    )


def _ok(body: Dict[str, Any]):
    return lambda _request, _n: httpx.Response(200, json=body)


def _anchor(code: str, message: str = "no company"):
    """Sorento's FLAT anchor 422 - top level, no ``detail`` wrapper (A6)."""
    return lambda _request, _n: httpx.Response(
        422, json={"message": message, "detail": None, "code": code}
    )


def _customer(ref: str = "AED:1") -> CanonicalCustomer:
    return CanonicalCustomer(source_ref=ref, code="300-A001", name="Acme")


INGEST_OK = {
    "summary": {"total": 1, "created": 1, "updated": 0, "failed": 0, "retryable": 0},
    "records": [{"source_ref": "AED:1", "outcome": "created", "entity_id": "c-1"}],
}


# ── companyCode on EVERY call (A6) ───────────────────────────────────────────


def test_ingest_carries_the_company_code_at_the_TOP_LEVEL():
    sink, rec = _sink(_ok(INGEST_OK))
    sink.write_batch([_customer()], request_id="r1")
    assert rec.requests[0]["json"]["companyCode"] == CODE
    assert rec.requests[0]["path"] == "/api/v1/external/ingest/customers"


def test_the_dry_run_carries_it_too():
    sink, rec = _sink(_ok(INGEST_OK))
    sink.dry_run([_customer()])
    assert rec.requests[0]["json"]["companyCode"] == CODE
    assert rec.requests[0]["params"] == {"dry_run": "true"}


def test_the_read_back_carries_it_too():
    sink, rec = _sink(_ok({"records": [], "not_found": []}))
    sink.read_back(["AED:1"])
    assert rec.requests[0]["json"] == {"companyCode": CODE, "source_refs": ["AED:1"]}
    assert rec.requests[0]["path"] == "/api/v1/external/read/customers"


def test_the_deletion_call_carries_it_too():
    sink, rec = _sink(_ok({"summary": {}, "records": []}))
    sink.delete_batch(["AED:1"])
    assert rec.requests[0]["json"] == {"companyCode": CODE, "source_refs": ["AED:1"]}
    assert rec.requests[0]["path"] == "/api/v1/external/ingest/customers/deletions"


def test_a_blank_company_code_is_OMITTED_so_sorento_answers_authoritatively():
    """We never guess Sorento's anchor rules locally - a missing code goes out
    absent and comes back as ``COMPANY_ANCHOR_REQUIRED`` from the only party
    that can decide it."""
    sink, rec = _sink(_anchor(COMPANY_ANCHOR_REQUIRED), company_code=None)
    with pytest.raises(SinkAnchorError):
        sink.write_batch([_customer()], request_id="r1")
    assert "companyCode" not in rec.requests[0]["json"]


def test_the_code_comes_from_the_COMPANY_not_the_connection():
    """One Sorento connection legitimately serves several AutoCount companies;
    anchoring on the connection would cross-post their masters."""
    sink = sorento_sink_from_connection(
        {"baseUrl": "https://sorento.example.com"},
        {"apiKey": "key-1"},
        entity_type=ENTITY_CUSTOMER,
        company_code=" srt-2 ",
    )
    assert sink.company_code == "srt-2"


# ── the four anchor codes → a TASK-level error (A6/A7 §2) ────────────────────


@pytest.mark.parametrize(
    "code",
    [
        COMPANY_ANCHOR_REQUIRED,
        UNKNOWN_COMPANY,
        COMPANY_BINDING_INVALID,
        COMPANY_ANCHOR_AMBIGUOUS,
    ],
)
def test_every_anchor_code_raises_a_typed_task_level_error(code):
    sink, _rec = _sink(_anchor(code, "the anchor is wrong"))
    with pytest.raises(SinkAnchorError) as exc:
        sink.write_batch([_customer()], request_id="r1")
    assert exc.value.code == code
    assert exc.value.sorento_message == "the anchor is wrong"
    # A subclass, so every existing caller still treats it as "nothing was
    # written, the whole batch is unresolved".
    assert isinstance(exc.value, SorentoSinkError)


def test_all_four_codes_are_declared():
    assert ANCHOR_ERROR_CODES == {
        COMPANY_ANCHOR_REQUIRED,
        UNKNOWN_COMPANY,
        COMPANY_BINDING_INVALID,
        COMPANY_ANCHOR_AMBIGUOUS,
    }


def test_an_anchor_error_on_the_dry_run_is_the_same_typed_error():
    sink, _rec = _sink(_anchor(UNKNOWN_COMPANY))
    with pytest.raises(SinkAnchorError) as exc:
        sink.dry_run([_customer()])
    assert exc.value.code == UNKNOWN_COMPANY


def test_a_422_that_is_NOT_an_anchor_error_stays_a_generic_batch_failure():
    """Mislabelling a validation 422 as an anchor problem would send an
    operator to change the company code over a data fault."""
    responder = lambda _r, _n: httpx.Response(  # noqa: E731 - one-line stub
        422, json={"message": "bad body", "detail": None, "code": "INVALID_BODY"}
    )
    sink, _rec = _sink(responder)
    with pytest.raises(SorentoSinkError) as exc:
        sink.write_batch([_customer()], request_id="r1")
    assert not isinstance(exc.value, SinkAnchorError)


def test_a_422_with_an_unparseable_body_is_a_generic_failure_not_a_crash():
    responder = lambda _r, _n: httpx.Response(422, content=b"<html>nope</html>")  # noqa: E731
    sink, _rec = _sink(responder)
    with pytest.raises(SorentoSinkError) as exc:
        sink.write_batch([_customer()], request_id="r1")
    assert not isinstance(exc.value, SinkAnchorError)


# ── read-back (A7 §3/§4, A8) ─────────────────────────────────────────────────


def test_read_back_returns_the_records_and_not_found_envelope():
    sink, _rec = _sink(
        _ok({"records": [{"source_ref": "AED:1", "entity_id": "c-1"}], "not_found": ["AED:9"]})
    )
    body = sink.read_back(["AED:1", "AED:9"])
    assert body["not_found"] == ["AED:9"]
    assert body["records"][0]["source_ref"] == "AED:1"


def test_read_back_numbers_parse_into_Decimal_via_str_never_a_float():
    """A 4-dp quantity round-tripped through binary floating point comes back
    subtly different, and the diff layer then reports a change that is not
    there (A7 §3)."""
    sink, _rec = _sink(
        _ok(
            {
                "records": [
                    {
                        "source_ref": "AED:1",
                        "credit_limit": 12.3456,
                        "lines": [{"qty_ordered": 1.1, "unit_price": 0.1}],
                    }
                ],
                "not_found": [],
            }
        )
    )
    record = sink.read_back(["AED:1"])["records"][0]
    assert record["credit_limit"] == Decimal("12.3456")
    assert record["lines"][0]["qty_ordered"] == Decimal("1.1")
    # The float-constructed value is NOT what we want, and this proves it.
    assert record["lines"][0]["unit_price"] != Decimal(0.1)
    assert record["lines"][0]["unit_price"] == Decimal("0.1")


def test_read_back_leaves_booleans_and_strings_alone():
    sink, _rec = _sink(
        _ok({"records": [{"is_active": True, "code": "300-A001"}], "not_found": []})
    )
    record = sink.read_back(["AED:1"])["records"][0]
    assert record["is_active"] is True
    assert record["code"] == "300-A001"


def test_read_back_tolerates_a_line_we_never_sent(rig=None):
    """A7 §1: a line absent from a re-push is CANCELLED IN PLACE when something
    references it, so read-back can return lines we never sent. The sink must
    hand them back untouched rather than treating them as drift."""
    sink, _rec = _sink(
        _ok(
            {
                "records": [
                    {
                        "source_ref": "AED:1",
                        "lines": [
                            {"source_ref": "L1", "qty_ordered": 2},
                            {"source_ref": "L-GHOST", "line_status": "cancelled", "qty_ordered": 5},
                        ],
                    }
                ],
                "not_found": [],
            }
        )
    )
    lines = sink.read_back(["AED:1"])["records"][0]["lines"]
    assert [line["source_ref"] for line in lines] == ["L1", "L-GHOST"]
    assert lines[1]["line_status"] == "cancelled"


# ── chunking: ONE data path for dry-run and push ─────────────────────────────


def test_the_dry_run_chunks_at_the_vendor_ceiling_like_the_push():
    """An initial-load dry run (the activation gate) is routinely bigger than
    one batch; an over-size body is a 413, which would make the gate
    un-passable on exactly the companies that most need it."""
    seen: List[int] = []

    def responder(request: httpx.Request, _n: int) -> httpx.Response:
        import json

        records = json.loads(request.content)["records"]
        seen.append(len(records))
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(records), "created": len(records),
                    "updated": 0, "failed": 0, "retryable": 0,
                },
                "records": [
                    {"source_ref": r["source_ref"], "outcome": "created"} for r in records
                ],
            },
        )

    sink, _rec = _sink(responder)
    records = [_customer(f"AED:{i}") for i in range(SORENTO_MAX_BATCH + 5)]
    result = sink.dry_run(records)
    assert seen == [SORENTO_MAX_BATCH, 5]
    # The summaries MERGE - a per-chunk summary would under-report the batch.
    assert result.summary["created"] == SORENTO_MAX_BATCH + 5
    assert len(result.predictions) == SORENTO_MAX_BATCH + 5


def test_an_empty_dry_run_makes_no_call_at_all():
    sink, rec = _sink(_ok(INGEST_OK))
    result = sink.dry_run([])
    assert rec.requests == []
    assert result.summary["total"] == 0


# ── verdicts are UNCHANGED by the anchor work ────────────────────────────────


def test_per_record_verdicts_still_decide_delivery_not_the_http_status():
    sink, _rec = _sink(
        _ok(
            {
                "summary": {"total": 2, "created": 1, "updated": 0, "failed": 1, "retryable": 0},
                "records": [
                    {"source_ref": "AED:1", "outcome": "created", "entity_id": "c-1"},
                    {"source_ref": "AED:2", "outcome": "failed", "errors": {"code": "too long"}},
                ],
            }
        )
    )
    results = sink.write_batch([_customer("AED:1"), _customer("AED:2")], request_id="r1")
    assert [r.delivered for r in results] == [True, False]
    assert results[0].external_id == "c-1"
    assert "too long" in results[1].message


def test_deletion_verdicts_come_back_per_ref():
    sink, _rec = _sink(
        _ok(
            {
                "summary": {
                    "total": 3, "deleted": 1, "deactivated": 1, "not_found": 1, "failed": 0
                },
                "records": [
                    {"source_ref": "AED:1", "outcome": "deleted", "entity_id": "c-1"},
                    {"source_ref": "AED:2", "outcome": "deactivated", "entity_id": "c-2"},
                    {"source_ref": "AED:3", "outcome": "not_found"},
                ],
            }
        )
    )
    body = sink.delete_batch(["AED:1", "AED:2", "AED:3"])
    assert body["summary"]["deleted"] == 1
    assert [r["outcome"] for r in body["records"]] == [
        "deleted", "deactivated", "not_found"
    ]
