"""Dashboards review-fix red tests (body cap, catalogue caps, image precheck, usage on failure,
agent connection kept, delete clears idempotency, Anthropic body key order)."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.ai.stub import StubResponse, stub_fixtures
from tests.dashboards_helpers import dash, llm  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import (
    BASE,
    CATALOGUE,
    OWNER,
    add_op,
    assert_flat_error,
    assert_plain,
    delete,
    f1_spec,
    f1_tiles,
    get,
    hdr,
    new_idem,
    ops_out,
    save,
    turn,
    usage_rows,
)

JSON_CT = {"Content-Type": "application/json"}


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


# -- 1. body cap -----------------------------------------------------------------------------------

def test_two_mb_save_body_without_key_is_413_not_401_or_422(client, dash):
    body = json.dumps({"pad": "a" * (2 * 1024 * 1024)}).encode()
    res = client.post(f"{BASE}/save", content=body, headers=JSON_CT)
    assert res.status_code == 413, (res.status_code, res.text[:200])


def test_two_mb_body_on_another_non_turn_route_is_413(client, dash):
    body = json.dumps({"actor_ref": OWNER, "pad": "a" * (2 * 1024 * 1024)}).encode()
    res = client.post(f"{BASE}/d_x/share", content=body, headers={**JSON_CT, **hdr(dash.sorento)})
    assert res.status_code == 413, (res.status_code, res.text[:200])


def test_builder_turn_over_24_mb_is_413_before_key_check(client, dash):
    body = json.dumps({"pad": "a" * (25 * 1024 * 1024)}).encode()
    res = client.post(f"{BASE}/builder/turn", content=body, headers=JSON_CT)
    assert res.status_code == 413, (res.status_code, res.text[:200])


def test_builder_turn_2mb_body_is_not_capped_by_the_one_mb_rule(client, dash):
    body = json.dumps({"pad": "a" * (2 * 1024 * 1024)}).encode()
    res = client.post(f"{BASE}/builder/turn", content=body, headers=JSON_CT)
    assert res.status_code == 401, (res.status_code, res.text[:200])  # no key, under the 24 MB cap


def test_normal_requests_are_unaffected_by_the_cap(client, dash):
    assert save(client, dash.sorento, OWNER, "Normal", f1_spec()).status_code == 200
    assert client.post(f"{BASE}/save", json={"actor_ref": OWNER}).status_code == 401


# -- 2. catalogue caps -----------------------------------------------------------------------------

def _cat_with(n_entities: int):
    cat = copy.deepcopy(CATALOGUE)
    base = cat["entities"][0]
    cat["entities"] = []
    for i in range(n_entities):
        e = copy.deepcopy(base)
        e["entity"] = f"ent_{i}"
        cat["entities"].append(e)
    return cat


def test_forty_entities_is_fine_forty_one_is_refused(client, dash, llm):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", catalogue_=_cat_with(40)))
    n = llm.n
    body = assert_flat_error(turn(client, dash.sorento, OWNER, "x", catalogue_=_cat_with(41)), 422, "spec_invalid")
    assert_plain(body["problems"])
    assert llm.n == n


def test_index_over_20kb_is_refused_without_an_llm_call(client, dash, llm):
    cat = copy.deepcopy(CATALOGUE)
    cat["index"].append({"entity": "big_one", "label": "x" * 21000, "module": "sales"})
    body = assert_flat_error(turn(client, dash.sorento, OWNER, "x", catalogue_=cat), 422, "spec_invalid")
    assert_plain(body["problems"])
    assert llm.n == 0


def test_whole_catalogue_over_800kb_is_refused_without_an_llm_call(client, dash, llm):
    cat = _cat_with(40)
    for e in cat["entities"]:
        e["default_note"] = "n" * 20000
    assert len(json.dumps(cat, separators=(",", ":"))) > 800_000
    body = assert_flat_error(turn(client, dash.sorento, OWNER, "x", catalogue_=cat), 422, "spec_invalid")
    assert_plain(body["problems"])
    assert llm.n == 0


def _refusal(**kw):
    r = {"tile_id": "t1", "code": "no_match", "reason": "No customer by that name.", "candidates": ["A", "B"]}
    r.update(kw)
    return r


def test_refusal_reason_300_ok_301_refused(client, dash, llm):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", refusals=[_refusal(reason="r" * 300)]))
    n = llm.n
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", refusals=[_refusal(reason="r" * 301)]), 422, "spec_invalid")
    assert llm.n == n


def test_refusal_candidates_cap_five_items_of_80_chars(client, dash, llm):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", refusals=[_refusal(candidates=["c" * 80] * 5)]))
    n = llm.n
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", refusals=[_refusal(candidates=["a"] * 6)]), 422, "spec_invalid")
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", refusals=[_refusal(candidates=["c" * 81])]), 422, "spec_invalid")
    assert llm.n == n


# -- 3. image size precheck ------------------------------------------------------------------------

def test_oversized_base64_is_refused_without_decoding(client, dash, monkeypatch, llm):
    import base64

    import modules.dashboards.services.builder_service as bs

    big = "A" * (6990507 + 4 + 1)  # one over ceil(5 MB * 4/3) + 4
    seen = []
    real = base64.b64decode

    def counting(s, *a, **k):
        seen.append(len(s))
        return real(s, *a, **k)

    monkeypatch.setattr(bs.base64, "b64decode", counting)
    res = turn(client, dash.sorento, OWNER, "x", images=[{"name": "a.png", "media_type": "image/png", "data_base64": big}])
    assert_flat_error(res, 422, "images_invalid")
    assert len(big) not in seen, "the oversized image was decoded before being refused"
    assert llm.n == 0


# -- 4. usage on LLM failure -----------------------------------------------------------------------

def test_llm_failure_still_writes_exactly_one_usage_row(client, dash):
    tid = new_idem()
    with stub_fixtures(StubResponse(error="boom")):
        res = turn(client, dash.sorento, OWNER, "x", turn_id=tid)
    assert_flat_error(res, 502, "ai_failed")
    rows = usage_rows(dash.sf)
    assert len(rows) == 1, rows
    r = rows[0]
    assert (r.tokens_in, r.tokens_out, r.llm_calls, r.turn_id) == (0, 0, 1, tid)


# -- 5. agent connection not clobbered -------------------------------------------------------------

def _conn(db, provider, created_at=None, tenant_id=None):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret
    from tests.conftest import DEFAULT_TENANT_ID

    c = Connection(tenant_id=tenant_id or DEFAULT_TENANT_ID, provider=provider, type="llm", name=f"{provider} {new_idem()[:6]}",
                   config_json={}, credentials_json=encrypt_secret({"apiKey": "x", "dev": True}))
    if created_at:
        c.created_at = created_at
    db.add(c)
    db.commit()
    db.refresh(c)
    return c.id


def _agent_conn(sf):
    from app.models.ai import AiAgent

    db = sf()
    try:
        a = db.query(AiAgent).filter(AiAgent.key == "dashboard-builder").one()
        return a.connection_id
    finally:
        db.close()


def _set_agent_conn(sf, conn_id):
    from app.models.ai import AiAgent

    db = sf()
    try:
        a = db.query(AiAgent).filter(AiAgent.key == "dashboard-builder").one()
        a.connection_id = conn_id
        db.commit()
    finally:
        db.close()


def _one_turn(client, dash):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x"))


def test_a_tenant_chosen_newer_anthropic_connection_is_kept(client, dash):
    # one anthropic row per tenant (DB unique), so the "second, newer" one is the platform tenant's
    from app.models.tenant import PLATFORM_TENANT_ID

    db = dash.sf()
    try:
        _conn(db, "anthropic", datetime.now(timezone.utc) - timedelta(days=2))
        mine = _conn(db, "anthropic", datetime.now(timezone.utc), tenant_id=PLATFORM_TENANT_ID)
    finally:
        db.close()
    _one_turn(client, dash)
    _set_agent_conn(dash.sf, mine)
    _one_turn(client, dash)
    assert _agent_conn(dash.sf) == mine


@pytest.mark.parametrize("bad", ["null", "gemini"])
def test_null_or_non_anthropic_agent_connection_is_replaced_by_an_anthropic_one(client, dash, bad):
    db = dash.sf()
    try:
        anth = _conn(db, "anthropic", datetime.now(timezone.utc) - timedelta(days=2))
        other = _conn(db, "gemini")
    finally:
        db.close()
    _one_turn(client, dash)
    _set_agent_conn(dash.sf, None if bad == "null" else other)
    _one_turn(client, dash)
    assert _agent_conn(dash.sf) == anth


# -- 6. delete clears idempotency ------------------------------------------------------------------

def test_save_after_delete_with_the_same_idempotency_key_creates_afresh(client, dash):
    k = new_idem()
    first = ok(save(client, dash.sorento, OWNER, "Once", f1_spec(), idempotency_key=k))
    assert delete(client, dash.sorento, OWNER, first["id"]).status_code == 200
    again = save(client, dash.sorento, OWNER, "Once", f1_spec(), idempotency_key=k)
    body = ok(again)
    assert body["id"] != first["id"]
    assert get(client, dash.sorento, OWNER, first["id"]).status_code == 404
    assert get(client, dash.sorento, OWNER, body["id"]).status_code == 200


# -- 7. Anthropic request body key order (matches main) --------------------------------------------

def test_anthropic_body_key_order_for_an_older_model_matches_main(monkeypatch):
    import app.integrations.anthropic_provider as ap

    seen = {}

    def fake(method, url, **kw):
        seen["body"] = kw["json_body"]
        return {"content": [{"type": "tool_use", "name": "emit_result", "input": {}}],
                "usage": {"input_tokens": 1, "output_tokens": 1}, "stop_reason": "tool_use"}

    monkeypatch.setattr(ap, "_http_json", fake)
    ap.AnthropicProvider().complete({}, {"apiKey": "k"}, model="claude-sonnet-4-6", system="sys",
                                    messages=[{"role": "user", "content": "hi"}],
                                    output_schema={"type": "object"}, temperature=0.0)
    assert list(seen["body"].keys()) == ["model", "max_tokens", "temperature", "messages", "system", "tools", "tool_choice"]
