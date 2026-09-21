"""Sprint-5/10 S5a follow-up - the ``POST /autocount/http/preview`` funnel
(AC-10-82's own "Test shows the FUNNEL" text), the piece the S5a coder left
deferred: when a task carries a ``combine`` block, Test must run combine on
the sampled page and show rows in -> excluded -> groups -> dropped per
rule -> rows out, alongside the combined rows in the existing preview grid.

Wire shape (coordinator ruling, additive over the existing
``HttpPreviewResponse``): ``rowsIn``, ``excludedCount``, ``groups``,
``droppedByRule: {<rule>: count}``, ``rowsOut``, ``roundedCount`` - ALL
``None``/absent for a plain preview with no ``combine`` key on the request,
so that response stays exactly as it was before this change (pinned below).
``rows``/``columns`` become the COMBINED shape (groupBy + carry + measure
aliases) in that same case, mirroring the push path's own stage order
(AC-10-80: combine runs after every lookup, before de-dup/hash/mapping).

The full-funnel fixture (``_funnel_rows``/``STOCK_COMBINE``) is the SAME
deterministic set ``test_s10_s5a_combine_apply.py`` already pins at the
``apply_combine`` layer (9 rows in, 2 excluded, 4 groups, "zero" drops 1,
"negative" drops 1, 1 rounded, 2 rows out) - duplicated here (house
convention: every preview-route test file owns its own fixtures, see
``test_s10_preview_lookups_route.py``) to prove the SAME numbers survive
the trip through the HTTP route, not just the bare reducer.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection

STOCK_COMBINE: Dict[str, Any] = {
    "computed": [
        {"alias": "item_code", "formula": "trim(ItemCode)"},
        {"alias": "location_code", "formula": "trim(Location)"},
        {
            "alias": "base_qty",
            "formula": (
                "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                "number(BalQty), number(BalQty) * number(UomRate))"
            ),
        },
    ],
    "require": [
        {
            "name": "uom_rate",
            "formula": (
                "lower(trim(UOM)) == lower(trim(ItemBaseUOM)) or "
                "number(default(UomRate, 0)) > 0"
            ),
            "reason": "uom_rate_unresolved",
        }
    ],
    "measure": "base_qty",
    "groupBy": ["item_code", "location_code"],
    "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
    "carry": ["ItemDescription", "ItemBaseUOM"],
    "round": [{"measure": "qty", "mode": "half_up", "dp": 0}],
    "drop": [
        {"name": "zero", "formula": "qty == 0"},
        {"name": "negative", "formula": "qty < 0", "listRows": True},
    ],
}


def _row(**kw: Any) -> Dict[str, Any]:
    base = {
        "ItemCode": "X", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "Location": "L",
        "BatchNo": "", "BalQty": 1, "ItemDescription": "Item", "UomRate": 1.0,
    }
    base.update(kw)
    return base


def _funnel_rows() -> List[Dict[str, Any]]:
    return [
        _row(ItemCode="SRT-01", UOM="UNIT", Location="MAIN", BalQty=10,
             ItemDescription="Widget-First"),
        _row(ItemCode="SRT-01", UOM="BOX", Location="MAIN", BalQty=2, UomRate=5.0,
             ItemDescription="Widget-Second"),
        _row(ItemCode="SRT-02", UOM="UNIT", Location="MBS ", BalQty=5,
             ItemDescription="Gadget"),
        _row(ItemCode="SRT-02", UOM="UNIT", Location="MBS", BalQty=-8,
             ItemDescription="Gadget"),
        _row(ItemCode="SRT-03", UOM="UNIT", Location="LOC1", BalQty=0,
             ItemDescription="Thing"),
        _row(ItemCode="SRT-04", UOM="BOX", Location="LOC2", BalQty=3, UomRate=0,
             ItemDescription="Thing2"),
        {
            "ItemCode": "SRT-05", "UOM": "BOX", "ItemBaseUOM": "UNIT",
            "Location": "LOC3", "BatchNo": "", "BalQty": 4,
            "ItemDescription": "Thing3",
        },
        _row(ItemCode="SRT-06", UOM="UNIT", Location="LOC4", BalQty=3,
             ItemDescription="Frac"),
        _row(ItemCode="SRT-06", UOM="BOX", Location="LOC4", BalQty=1, UomRate=0.5,
             ItemDescription="Frac"),
    ]


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _multi_transport(pages_by_path: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        status, body = pages_by_path[match]
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _preview(client, headers, db, **body_overrides: Any):
    """sprint-5/11 (AC-11-21/22) - ``POST /autocount/http/preview`` is now a
    202 job start; this starts it and (for a 202) immediately polls the job
    - under this suite's eager execution the job is ALREADY terminal by the
    time the POST returns, so ONE poll is enough. Returns the POLL response
    for a 202, or the POST response UNCHANGED for anything the pre-flight
    gate itself still rejects synchronously."""
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    rows = body_overrides.pop("rows", None)
    if rows is None:
        rows = _funnel_rows()
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": (200, {
            "TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": rows,
        }),
    })
    body = {"connectionId": conn.id, "path": "/itembypage", **body_overrides}
    try:
        response = client.post("/autocount/http/preview", json=body, headers=headers)
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    if response.status_code != 202:
        return response
    return client.get(f"/autocount/previews/{response.json()['jobId']}", headers=headers)


# ── no combine block: the response is unaffected ────────────────────────────


def test_no_combine_leaves_the_response_unaffected(client, headers, db):
    poll = _preview(client, headers, db, rows=_funnel_rows())
    assert poll.status_code == 200, poll.text
    poll_body = poll.json()
    assert poll_body["status"] == "done", poll_body
    body = poll_body["result"]["preview"]
    for key in (
        "rowsIn", "excludedCount", "groups", "droppedByRule", "rowsOut", "roundedCount",
        "preCombineColumns",
    ):
        assert body.get(key) is None, (key, body)
    assert len(body["rows"]) == len(_funnel_rows())
    column_names = {c["name"] for c in body["columns"]}
    assert column_names == set(_funnel_rows()[0].keys()) | {"UomRate"}, column_names


# ── the full funnel, byte-pinned against the reducer's own numbers ──────────


def test_combine_returns_the_funnel_and_the_combined_rows(client, headers, db):
    poll = _preview(client, headers, db, combine=STOCK_COMBINE)
    assert poll.status_code == 200, poll.text
    poll_body = poll.json()
    assert poll_body["status"] == "done", poll_body
    body = poll_body["result"]["preview"]

    assert body["rowsIn"] == 9, body
    assert body["excludedCount"] == 2, body
    assert body["groups"] == 4, body
    assert body["droppedByRule"] == {"zero": 1, "negative": 1}, body
    assert body["rowsOut"] == 2, body
    assert body["roundedCount"] == 1, body

    rows = body["rows"]
    assert len(rows) == 2, rows
    by_key = {(r["item_code"], r["location_code"]): r for r in rows}
    assert set(by_key) == {("SRT-01", "MAIN"), ("SRT-06", "LOC4")}, rows
    # A grouped ``Decimal`` measure wire-serialises as a STRING (no native
    # JSON decimal type - the same house convention every other
    # ``Dict[str, Any]`` row payload already follows).
    assert by_key[("SRT-01", "MAIN")]["qty"] == "20", rows
    assert by_key[("SRT-06", "LOC4")]["qty"] == "4", rows  # 3.5 half-up
    assert by_key[("SRT-01", "MAIN")]["ItemDescription"] == "Widget-First"

    column_names = {c["name"] for c in body["columns"]}
    assert column_names == {
        "item_code", "location_code", "ItemDescription", "ItemBaseUOM", "qty"
    }, column_names


# ── R5-A (review round 5) - preCombineColumns: raw+lookup+computed only ─────


def test_the_pre_combine_columns_carry_raw_and_computed_aliases_never_the_grouped_output(
    client, headers, db
):
    """The Source tab's group-by/measure/require pickers must stay
    PRE-combine (what a formula may REFERENCE), never the grouped
    ``combineOutputColumns`` shape - so ``qty`` (a `measures[].alias`, only
    created AFTER grouping) must NOT appear, while the combine's OWN
    `computed` aliases (`item_code`/`location_code`/`base_qty`, available to
    every LATER stage) must."""
    poll = _preview(client, headers, db, combine=STOCK_COMBINE)
    assert poll.status_code == 200, poll.text
    poll_body = poll.json()
    assert poll_body["status"] == "done", poll_body
    body = poll_body["result"]["preview"]
    pre_combine = set(body["preCombineColumns"])
    assert pre_combine == {
        "ItemCode", "UOM", "ItemBaseUOM", "Location", "BatchNo", "BalQty",
        "ItemDescription", "UomRate", "item_code", "location_code", "base_qty",
    }, pre_combine
    assert "qty" not in pre_combine, pre_combine


# ── a computed-stage runtime error surfaces as excludedCount ────────────────


def test_a_computed_stage_runtime_error_surfaces_as_excludedCount(client, headers, db):
    """One row's ``base_qty`` formula raises at RUN TIME (``UomRate``
    genuinely absent for that row, present on the OTHER row so the formula
    still parses at save time) - the row is excluded (reason
    ``computed_error``, per ``combine.py``'s own R11 ruling 1), which must
    reach the funnel's ``excludedCount`` the same way a ``require``
    exclusion already does, isolated here from any other exclusion path."""
    rows = [
        _row(ItemCode="X1", UOM="UNIT", ItemBaseUOM="UNIT", Location="L1", BalQty=1,
             UomRate=1.0),
        {
            "ItemCode": "X2", "UOM": "BOX", "ItemBaseUOM": "UNIT", "Location": "L2",
            "BatchNo": "", "BalQty": 4, "ItemDescription": "NoRate",
        },
    ]
    combine = {
        "computed": [
            {"alias": "item_code", "formula": "trim(ItemCode)"},
            {"alias": "location_code", "formula": "trim(Location)"},
            {
                "alias": "base_qty",
                "formula": (
                    "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                    "number(BalQty), number(BalQty) * number(UomRate))"
                ),
            },
        ],
        "require": [],
        "measure": "base_qty",
        "groupBy": ["item_code", "location_code"],
        "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
        "carry": [],
        "round": [],
        "drop": [],
    }
    poll = _preview(client, headers, db, rows=rows, combine=combine)
    assert poll.status_code == 200, poll.text
    poll_body = poll.json()
    assert poll_body["status"] == "done", poll_body
    body = poll_body["result"]["preview"]
    assert body["rowsIn"] == 2, body
    assert body["excludedCount"] == 1, body
    assert body["groups"] == 1, body
    assert body["droppedByRule"] == {}, body
    assert body["rowsOut"] == 1, body


# ── an invalid combine still 422s at preview time, never reaches apply ──────


def test_an_invalid_combine_422s_before_it_is_applied(client, headers, db):
    """sprint-5/11 (AC-11-21/22/25) - combine validation needs the sampled
    rows (``validate_combine(..., sample=result.rows)``), so it runs AFTER
    the network fetch - inside the job now, never a synchronous 422 (the
    same fieldErrors land on the FAILED job instead)."""
    bad_combine = {**STOCK_COMBINE, "groupBy": []}
    poll = _preview(client, headers, db, combine=bad_combine)
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "failed", body
    assert "combine.groupBy" in body["fieldErrors"]


# KILL TEST (for the reviewer): make ``EtlService.preview_http`` ignore its
# new ``combine`` parameter entirely (drop the branch that calls
# ``apply_combine``) - ``test_combine_returns_the_funnel_and_the_combined_
# rows`` flips red on every funnel/row assertion; the pre-existing
# ``test_preview_http_paged`` (test_autocount_http_task_config.py) and this
# file's own ``test_no_combine_leaves_the_response_unaffected`` stay green
# either way, proving a plain preview is unaffected by the new branch.
