"""AI dashboard builder S1 (SS) contract v2 red tests (wide vocabulary, images, lookup, set_layout, provider).

Contract: documentation/plans/ai-builder/SS-dashboards-contract.md (v2). Tests the wire, not the code.
"""
from __future__ import annotations

import copy
import json

import pytest

from app.ai.stub import StubResponse, stub_fixtures
from tests.dashboards_helpers import dash, llm  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import (
    CATALOGUE,
    FORBIDDEN,
    OWNER,
    SALES_ORDER_ENTITY,
    add_op,
    assert_flat_error,
    assert_plain,
    catalogue,
    create_dash,
    f1_tiles,
    get,
    image,
    need_out,
    new_idem,
    ops_out,
    save,
    turn,
    usage_rows,
    with_id,
)

SRC = {"kind": "query", "spec": {"entity": "billing_document",
                                  "group_by": ["customer_name"], "aggregates": [{"fn": "sum", "field": "sales_amount"}]}}


def vs(spec):
    from modules.dashboards.spec import validate_spec

    return validate_spec(spec)


def src(entity="billing_document"):
    return {"kind": "query", "spec": {"entity": entity, "aggregates": [{"fn": "count"}]}}


def t_(n=1, show="pie", **extra):
    t = {"id": f"t{n}", "title": f"Chart {n}", "show": show, "source": copy.deepcopy(SRC)}
    t.update(extra)
    return t


def spec_of(*tiles):
    return {"version": 1, "title": "Wide", "period": "this_year", "tiles": list(tiles)}


def series_tile(**kw):
    t = {"id": "t1", "title": "Two sources", "show": "combo",
         "series": [{"key": "s1", "label": "Sales", "source": src(), "as": "bar"},
                    {"key": "s2", "label": "Orders", "source": src("sales_order"), "as": "line"}]}
    t.update(kw)
    return t


WIDE_SHOWS = ["number", "kpi_target", "gauge", "line", "area", "bar", "stacked_bar", "combo", "pie",
              "scatter", "heatmap", "table", "pivot", "map", "widget"]
V2_SHOWS = ["kpi_target", "gauge", "area", "stacked_bar", "combo", "pie", "scatter", "heatmap", "pivot", "map", "widget"]


# -- 2. wide vocabulary is valid and saves (F17) ---------------------------------------------------

@pytest.mark.parametrize("show", V2_SHOWS)
def test_every_v2_show_value_validates(show):
    assert vs(spec_of(t_(1, show))) == []


@pytest.mark.parametrize("kind", ["report", "widget"])
def test_report_and_widget_source_kinds_validate(kind):
    t = t_(1, "table")
    t["source"]["kind"] = kind
    assert vs(spec_of(t)) == []


def test_series_calc_target_display_size_position_drill_validate():
    t = series_tile(
        calc=[{"key": "c1", "label": "Gap", "op": "difference", "args": ["s1.sum_sales_amount", "s2.count"]},
              {"key": "c2", "op": "percent_of_target", "args": ["s1.sum_sales_amount", "target"]},
              {"key": "c3", "op": "sum_of", "args": ["sum_sales_amount"]}],
        target={"value": 1000.5},
        display={"legend": True, "values": False, "stacked": True, "axis_min": 0, "axis_max": 10.5,
                 "top_n": 50, "other_bucket": True},
        size={"w": 4, "h": 1}, position={"x": 3, "y": 99}, drill="none")
    assert vs(spec_of(t)) == []


def test_target_by_source_and_drill_list_validate():
    t = t_(1, "gauge", target={"source": src("sales_order")}, drill="list")
    assert vs(spec_of(t)) == []


def test_series_with_one_and_four_items_validate():
    one = series_tile()
    one["series"] = one["series"][:1]
    assert vs(spec_of(one)) == []
    four = series_tile()
    four["series"] = [{"key": f"s{i}", "label": f"S{i}", "source": src()} for i in range(4)]
    assert vs(spec_of(four)) == []


def test_f17_save_pie_series_calc_returns_200_and_round_trips(client, dash):
    spec = spec_of(t_(1, "pie"),
                   series_tile(id="t2", calc=[{"key": "c1", "op": "ratio", "args": ["s1.count", "s2.count"]}]))
    res = save(client, dash.sorento, OWNER, "Wide", spec)
    assert res.status_code == 200, res.text
    assert "not available yet" not in res.text.lower()
    again = get(client, dash.sorento, OWNER, res.json()["id"]).json()
    assert again["spec"]["tiles"] == spec["tiles"] and not again.get("spec_problems")


@pytest.mark.parametrize("show", ["pivot", "widget"])
def test_save_pivot_and_widget_is_200(client, dash, show):
    res = save(client, dash.sorento, OWNER, "Wide", spec_of(t_(1, show)))
    assert res.status_code == 200, res.text


def test_save_report_kind_is_200(client, dash):
    t = t_(1, "table")
    t["source"]["kind"] = "report"
    assert save(client, dash.sorento, OWNER, "Wide", spec_of(t)).status_code == 200


def test_oneof_source_and_series_both_or_neither_refused():
    both = series_tile(source=copy.deepcopy(SRC))
    assert_plain(vs(spec_of(both)))
    neither = t_(1, "pie")
    del neither["source"]
    assert_plain(vs(spec_of(neither)))


# -- every new object refuses extra keys; out-of-range refused plainly -----------------------------

def _mut(fn):
    t = series_tile(calc=[{"key": "c1", "op": "ratio", "args": ["s1.count", "s2.count"]}],
                    target={"value": 1}, display={"legend": True}, size={"w": 1, "h": 1}, position={"x": 0, "y": 0})
    fn(t)
    return spec_of(t)


EXTRA = {
    "series_item": lambda t: t["series"][0].update(bogus=1),
    "calc": lambda t: t["calc"][0].update(bogus=1),
    "target": lambda t: t["target"].update(bogus=1),
    "display": lambda t: t["display"].update(bogus=1),
    "size": lambda t: t["size"].update(bogus=1),
    "position": lambda t: t["position"].update(bogus=1),
}


@pytest.mark.parametrize("name", sorted(EXTRA))
def test_new_objects_refuse_extra_keys(name):
    assert_plain(vs(_mut(EXTRA[name])))


BAD = {
    "series_5_items": lambda t: t.update(series=[{"key": f"s{i}", "label": "x", "source": src()} for i in range(5)]),
    "series_empty": lambda t: t.update(series=[]),
    "series_key_s10": lambda t: t["series"][0].update(key="s10"),
    "series_key_upper": lambda t: t["series"][0].update(key="S1"),
    "series_label_empty": lambda t: t["series"][0].update(label=""),
    "series_label_61": lambda t: t["series"][0].update(label="a" * 61),
    "series_as_pie": lambda t: t["series"][0].update(**{"as": "pie"}),
    "series_missing_source": lambda t: t["series"][0].pop("source"),
    "calc_key_c10": lambda t: t["calc"][0].update(key="c10"),
    "calc_bad_op": lambda t: t["calc"][0].update(op="median"),
    "calc_no_args": lambda t: t["calc"][0].update(args=[]),
    "calc_3_args": lambda t: t["calc"][0].update(args=["a", "b", "c"]),
    "calc_arg_upper": lambda t: t["calc"][0].update(args=["S1.x"]),
    "calc_arg_bad_series": lambda t: t["calc"][0].update(args=["s12.x"]),
    "calc_5_items": lambda t: t.update(calc=[{"key": f"c{i}", "op": "sum_of", "args": ["a"]} for i in range(5)]),
    "target_both": lambda t: t.update(target={"value": 1, "source": src()}),
    "target_neither": lambda t: t.update(target={}),
    "target_str": lambda t: t.update(target={"value": "ten"}),
    "top_n_0": lambda t: t["display"].update(top_n=0),
    "top_n_51": lambda t: t["display"].update(top_n=51),
    "legend_str": lambda t: t["display"].update(legend="yes"),
    "size_w_0": lambda t: t["size"].update(w=0),
    "size_w_5": lambda t: t["size"].update(w=5),
    "size_h_5": lambda t: t["size"].update(h=5),
    "size_missing_h": lambda t: t["size"].pop("h"),
    "pos_x_4": lambda t: t["position"].update(x=4),
    "pos_x_neg": lambda t: t["position"].update(x=-1),
    "pos_y_100": lambda t: t["position"].update(y=100),
    "pos_missing_y": lambda t: t["position"].pop("y"),
    "drill_open": lambda t: t.update(drill="open"),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_out_of_range_and_enum_values_refused_with_plain_reasons(name):
    assert_plain(vs(_mut(BAD[name])))


@pytest.mark.parametrize("seq", ["<", ">", "://", ";", "--", "/*", "\x07"])
@pytest.mark.parametrize("where", ["series_label", "calc_label"])
def test_forbidden_sequences_refused_in_new_strings(where, seq):
    def mutate(t):
        if where == "series_label":
            t["series"][0]["label"] = f"ab{seq}cd"
        else:
            t["calc"][0]["label"] = f"ab{seq}cd"

    problems = vs(_mut(mutate))
    assert_plain(problems)
    assert any(p["reason"] == FORBIDDEN for p in problems), problems


def test_not_available_yet_is_no_longer_a_save_refusal():
    for show in V2_SHOWS:
        problems = vs(spec_of(t_(1, show)))
        assert not any("not available yet" in p["reason"].lower() for p in problems), show


# -- 3. shape rules constrain only number/line/bar/table -------------------------------------------

def test_shape_rules_still_apply_to_the_four_and_not_to_the_rest():
    bad_number = t_(1, "number")  # grouped, so refused as a number
    assert_plain(vs(spec_of(bad_number)))
    pie_ungrouped = t_(1, "pie")
    pie_ungrouped["source"]["spec"].pop("group_by")
    assert vs(spec_of(pie_ungrouped)) == []
    scatter_one_agg = t_(2, "scatter")
    assert vs(spec_of(scatter_one_agg)) == []


# -- 4. builder turn: images, turn_id, catalogue v2 ------------------------------------------------

def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def test_f15_six_images_refused(client, dash, llm):
    res = turn(client, dash.sorento, OWNER, "x", images=[image() for _ in range(6)])
    assert_flat_error(res, 422, "images_invalid")
    assert llm.n == 0


def test_five_images_accepted(client, dash):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", images=[image() for _ in range(5)]))


def test_f15_image_over_5mb_refused(client, dash, llm):
    res = turn(client, dash.sorento, OWNER, "x", images=[image(size=5 * 1024 * 1024 + 1)])
    assert_flat_error(res, 422, "images_invalid")
    assert llm.n == 0


def test_image_of_exactly_5mb_accepted(client, dash):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", images=[image(size=5 * 1024 * 1024)]))


def test_total_over_15mb_refused_even_when_each_is_under_5mb(client, dash, llm):
    imgs = [image(size=4 * 1024 * 1024) for _ in range(4)]  # 16 MB total
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", images=imgs), 422, "images_invalid")
    assert llm.n == 0


def test_f15_gif_refused(client, dash):
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", images=[image("image/gif")]), 422, "images_invalid")


@pytest.mark.parametrize("mt", ["image/png", "image/jpeg", "image/webp"])
def test_allowed_media_types_accepted(client, dash, mt):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", images=[image(mt)]))


def test_bad_base64_refused_with_images_invalid(client, dash):
    bad = {"name": "a.png", "media_type": "image/png", "data_base64": "!!!not base64!!!"}
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", images=[bad]), 422, "images_invalid")


def test_images_invalid_reason_is_plain(client, dash):
    body = assert_flat_error(turn(client, dash.sorento, OWNER, "x", images=[image("image/gif")]), 422, "images_invalid")
    assert_plain([{"path": "images", "reason": body["message"]}])


def test_f16_one_image_returns_f1_tiles_and_logs_a_count_only(client, dash):
    t1, t2 = f1_tiles()
    img = image(size=64)
    with stub_fixtures(ops_out("Added.", add_op(t1, "t7"), add_op(t2, "t8"))):
        body = ok(turn(client, dash.sorento, OWNER, "make it look like this", images=[img]))
    assert body["draft"]["tiles"] == f1_tiles() and body["changed_tile_ids"] == ["t1", "t2"]
    rows = usage_rows(dash.sf)
    assert len(rows) == 1 and rows[0].image_count == 1


def test_no_images_logs_count_zero(client, dash):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x"))
    assert usage_rows(dash.sf)[0].image_count == 0


def test_image_bytes_are_never_stored_anywhere(client, dash):
    import base64

    raw = b"UNIQUE-IMAGE-BYTES-0123456789"
    data = base64.b64encode(raw).decode()
    img = {"name": "secret-name.png", "media_type": "image/png", "data_base64": data}
    with stub_fixtures(ops_out("ok", add_op(f1_tiles()[0]))):
        ok(turn(client, dash.sorento, OWNER, "x", images=[img]))
    from modules.dashboards.db import DashboardsBase

    db = dash.sf()
    try:
        dumped = ""
        for table in DashboardsBase.metadata.sorted_tables:
            for row in db.execute(table.select()).fetchall():
                dumped += repr(tuple(row))
    finally:
        db.close()
    assert dumped, "usage row should exist"
    assert data not in dumped and raw.decode() not in dumped and data[:12] not in dumped


def test_images_reach_the_model_as_image_content_blocks(client, dash, llm):
    import base64

    data = base64.b64encode(b"IMG-MARKER-ABCDEF").decode()
    img = {"name": "a.jpg", "media_type": "image/jpeg", "data_base64": data}
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "read this", images=[img]))
    blob = json.dumps(llm.calls[0].get("messages"), default=str)
    assert "image/jpeg" in blob and data in blob


def test_no_images_means_no_image_blocks(client, dash, llm):
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "read this"))
    assert "image/" not in json.dumps(llm.calls[0].get("messages"), default=str)


def test_turn_id_is_required(client, dash, llm):
    from tests.dashboards_helpers import BASE, empty_draft, hdr

    body = {"actor_ref": OWNER, "dashboard_id": None, "draft": empty_draft(), "message": "x",
            "catalogue": copy.deepcopy(CATALOGUE), "refusals": [], "history": []}
    res = client.post(f"{BASE}/builder/turn", json=body, headers=hdr(dash.sorento))
    assert res.status_code == 422, res.text
    assert llm.n == 0


def test_turn_id_longer_than_64_refused(client, dash, llm):
    assert turn(client, dash.sorento, OWNER, "x", turn_id="a" * 65).status_code == 422
    assert llm.n == 0
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x", turn_id="a" * 64))


def test_catalogue_v2_validated_against_entities_not_index(client, dash):
    cat = catalogue()
    assert set(cat) >= {"version", "draws", "index", "entities", "buckets", "aggregates", "limits"} and cat["version"] == 2
    t1, t2 = f1_tiles()
    with stub_fixtures(ops_out("ok", add_op(t1), add_op(t2))):
        assert ok(turn(client, dash.sorento, OWNER, "x", catalogue_=cat))["changed_tile_ids"] == ["t1", "t2"]
    # index lists sales_order but entities does not: a tile on it is refused (full entries are the gate)
    so = {"id": "t1", "title": "Orders", "show": "number",
          "source": {"kind": "query", "spec": {"entity": "sales_order", "aggregates": [{"fn": "count"}]}}}
    with stub_fixtures(ops_out("o", add_op(so)), ops_out("o", add_op(so))):
        assert_flat_error(turn(client, dash.sorento, OWNER, "orders", catalogue_=cat), 502, "ai_failed")


def test_malformed_v2_catalogue_is_422(client, dash):
    assert_flat_error(turn(client, dash.sorento, OWNER, "x", catalogue_={"version": 2, "index": []}), 422, "spec_invalid")


# -- 5. lookup (F14) -------------------------------------------------------------------------------

def _so_tile():
    return {"id": "t1", "title": "Orders by month", "show": "line",
            "source": {"kind": "query", "spec": {"entity": "sales_order",
                                                 "group_by": [{"field": "order_date", "bucket": "month"}],
                                                 "aggregates": [{"fn": "sum", "field": "order_total"}]}}}


def _lookup_cat(with_so: bool):
    cat = catalogue()
    if with_so:
        cat["entities"].append(copy.deepcopy(SALES_ORDER_ENTITY))
    return cat


def test_f14_need_entities_round_then_repeat_adds_the_tile(client, dash):
    tid = new_idem()
    with stub_fixtures(need_out("sales_order")):
        body = ok(turn(client, dash.sorento, OWNER, "add sales orders by month",
                       catalogue_=_lookup_cat(False), turn_id=tid))
    assert body["need_entities"] == ["sales_order"]
    assert body["draft"]["tiles"] == [] and body["changed_tile_ids"] == []
    assert body["reply"] is None and body["question"] is None
    assert {"tokens_in", "tokens_out", "model"} <= set(body["usage"])
    with stub_fixtures(ops_out("Added.", add_op(_so_tile()))):
        body2 = ok(turn(client, dash.sorento, OWNER, "add sales orders by month",
                        catalogue_=_lookup_cat(True), turn_id=tid))
    assert len(body2["draft"]["tiles"]) == 1 and body2["draft"]["tiles"][0]["source"]["spec"]["entity"] == "sales_order"
    assert body2["changed_tile_ids"] == ["t1"] and not body2.get("need_entities")


def test_each_lookup_round_writes_one_usage_row_with_the_same_turn_id(client, dash):
    tid = new_idem()
    with stub_fixtures(need_out("sales_order", tokens_in=90, tokens_out=10)):
        ok(turn(client, dash.sorento, OWNER, "orders", catalogue_=_lookup_cat(False), turn_id=tid))
    with stub_fixtures(ops_out("Added.", add_op(_so_tile()), tokens_in=200, tokens_out=30)):
        ok(turn(client, dash.sorento, OWNER, "orders", catalogue_=_lookup_cat(True), turn_id=tid))
    rows = usage_rows(dash.sf)
    assert len(rows) == 2 and {r.turn_id for r in rows} == {tid}
    assert sorted((r.tokens_in, r.tokens_out) for r in rows) == [(90, 10), (200, 30)]


def test_entities_not_in_index_are_dropped_from_need_entities(client, dash):
    with stub_fixtures(need_out("payroll", "sales_order")):
        body = ok(turn(client, dash.sorento, OWNER, "orders", catalogue_=_lookup_cat(False)))
    assert body["need_entities"] == ["sales_order"]


def test_normal_turn_has_no_need_entities_and_its_own_turn_id_row(client, dash):
    tid = new_idem()
    with stub_fixtures(ops_out("ok")):
        body = ok(turn(client, dash.sorento, OWNER, "x", turn_id=tid))
    assert not body.get("need_entities")
    assert usage_rows(dash.sf)[0].turn_id == tid


# -- 6. set_layout ---------------------------------------------------------------------------------

def test_set_layout_changes_layout_only_and_is_not_a_changed_tile(client, dash):
    draft = {"version": 1, "title": "D", "period": "this_year", "tiles": f1_tiles()}
    op = {"op": "set_layout", "tile_id": "t1", "size": {"w": 2, "h": 3}, "position": {"x": 1, "y": 4}}
    with stub_fixtures(ops_out("Moved.", op)):
        body = ok(turn(client, dash.sorento, OWNER, "make the first one bigger", draft=draft))
    t1 = body["draft"]["tiles"][0]
    assert t1["size"] == {"w": 2, "h": 3} and t1["position"] == {"x": 1, "y": 4}
    base = {k: v for k, v in t1.items() if k not in ("size", "position")}
    assert base == f1_tiles()[0] and body["draft"]["tiles"][1] == f1_tiles()[1]
    assert body["changed_tile_ids"] == []
    assert [o["op"] for o in body["operations"]] == ["set_layout"]


def test_set_layout_out_of_range_is_not_applied(client, dash):
    draft = {"version": 1, "title": "D", "period": "this_year", "tiles": f1_tiles()}
    op = {"op": "set_layout", "tile_id": "t1", "size": {"w": 9, "h": 1}, "position": {"x": 0, "y": 0}}
    with stub_fixtures(ops_out("bad", op), ops_out("bad", op)):
        res = turn(client, dash.sorento, OWNER, "x", draft=draft)
    assert res.status_code == 502 or "size" not in res.json()["draft"]["tiles"][0]


# -- 7. builder on catalogue: PENDING crew decision (a) -------------------------------------------

def test_PENDING_DECISION_A_untouched_tile_with_missing_entity_does_not_fail_the_turn(client, dash):
    """Crew decision (a): a tile the turn did NOT touch, whose entity is absent from catalogue.entities
    (only in index), must not fail the turn. Flip this ONE test if the crew decides otherwise."""
    untouched = _so_tile()
    draft = {"version": 1, "title": "D", "period": "this_year", "tiles": [untouched]}
    with stub_fixtures(ops_out("Retitled.", {"op": "set_title", "title": "Renamed"})):
        res = turn(client, dash.sorento, OWNER, "rename it", draft=draft, catalogue_=_lookup_cat(False))
    body = ok(res)
    assert body["draft"]["title"] == "Renamed" and body["draft"]["tiles"] == [untouched]


def test_changed_tile_with_entity_missing_from_entities_is_refused(client, dash):
    draft = {"version": 1, "title": "D", "period": "this_year", "tiles": f1_tiles()}
    op = {"op": "change_tile", "tile_id": "t1", "tile": without_id_(_so_tile())}
    with stub_fixtures(ops_out("c", op), ops_out("c", op)):
        res = turn(client, dash.sorento, OWNER, "x", draft=draft, catalogue_=_lookup_cat(False))
    assert_flat_error(res, 502, "ai_failed")


def without_id_(t):
    t = copy.deepcopy(t)
    t.pop("id", None)
    return t


# -- 8. model + provider ---------------------------------------------------------------------------

def _llm_conn(db, provider, dev=True):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret
    from tests.conftest import DEFAULT_TENANT_ID

    c = Connection(tenant_id=DEFAULT_TENANT_ID, provider=provider, type="llm", name=f"{provider} key",
                   config_json={}, credentials_json=encrypt_secret({"apiKey": "x", "dev": True} if dev else {"apiKey": "x"}))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_builder_agent_model_is_claude_sonnet_5_5(client, dash):
    from app.models.ai import AiAgent

    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x"))
    db = dash.sf()
    try:
        assert "claude-sonnet-5-5" in {a.model for a in db.query(AiAgent).all()}
    finally:
        db.close()


def test_builder_resolves_the_tenants_anthropic_connection(client, dash):
    from app.models.ai import AiAgent

    db = dash.sf()
    try:
        _llm_conn(db, "gemini")  # older, must not be picked
        anth = _llm_conn(db, "anthropic")
        anth_id = anth.id
    finally:
        db.close()
    with stub_fixtures(ops_out("ok")):
        ok(turn(client, dash.sorento, OWNER, "x"))
    db = dash.sf()
    try:
        agents = [a for a in db.query(AiAgent).all() if a.model == "claude-sonnet-5-5"]
        assert agents and all(a.connection_id == anth_id for a in agents)
    finally:
        db.close()


def test_only_non_anthropic_connection_is_409_outside_development(client, dash, monkeypatch):
    from app.config import settings

    db = dash.sf()
    try:
        _llm_conn(db, "gemini")
    finally:
        db.close()
    monkeypatch.setattr(settings, "environment", "production")
    assert_flat_error(turn(client, dash.sorento, OWNER, "x"), 409, "ai_not_configured")
