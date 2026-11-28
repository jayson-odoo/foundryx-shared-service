"""AI dashboard builder S1 (SS) red tests: the spec validator (S-7). Contract section 2 + section 4.

``validate_spec(spec)`` and ``validate_against_catalogue(spec, catalogue)`` return a list of
``{"path", "reason"}`` (empty = ok). Reasons are plain words; never validator jargon.
"""
from __future__ import annotations

import copy
import json

import pytest

from tests.dashboards_helpers import (
    CATALOGUE,
    FORBIDDEN,
    NOT_YET,
    assert_plain,
    catalogue,
    catalogue_entity,
    f1_spec,
    f1_tiles,
)


def vs(spec):
    from modules.dashboards.spec import validate_spec

    return validate_spec(spec)


def vc(spec, cat=None):
    from modules.dashboards.spec import validate_against_catalogue

    return validate_against_catalogue(spec, cat if cat is not None else copy.deepcopy(CATALOGUE))


def tile(n: int = 1, show: str = "number", **spec):
    base = {"entity": "billing_document"}
    if show == "number":
        base["aggregates"] = [{"fn": "sum", "field": "sales_amount"}]
    elif show in ("line", "bar"):
        base["group_by"] = [{"field": "doc_date", "bucket": "month"}]
        base["aggregates"] = [{"fn": "count"}]
    elif show == "table":
        base["fields"] = ["doc_date", "customer_name"]
    base.update(spec)
    return {"id": f"t{n}", "title": f"Chart {n}", "show": show, "source": {"kind": "query", "spec": base}}


def spec_with(*tiles, title="Sales overview", period="this_year"):
    return {"version": 1, "title": title, "period": period, "tiles": list(tiles)}


def rich_spec():
    """Exercises every nested object kind so extra-key tests can poke each level."""
    t = tile(1, "bar")
    t["source"]["spec"].update({
        "filters": [{"field": "customer_name", "op": "eq", "value": "Fake Customer One"}],
        "group_by": [{"field": "doc_date", "bucket": "month"}],
        "aggregates": [{"fn": "sum", "field": "sales_amount"}],
        "sort": [{"field": "sum_sales_amount", "dir": "asc"}],
        "limit": 5,
    })
    return spec_with(t, period={"from": "2026-01-01", "to": "2026-03-31"})


# -- the happy shapes ------------------------------------------------------------------------------

def test_f1_tiles_validate_clean():
    assert vs(f1_spec()) == []
    assert vc(f1_spec()) == []


def test_rich_spec_validates_clean():
    assert vs(rich_spec()) == []
    assert vc(rich_spec()) == []


def test_all_named_periods_accepted():
    for p in ("today", "yesterday", "this_week", "last_week", "this_month", "last_month",
              "this_quarter", "last_quarter", "this_year", "last_year"):
        assert vs(spec_with(tile(1), period=p)) == [], p


def test_twelve_tiles_is_fine_and_thirteen_is_not():
    assert vs(spec_with(*[tile(i) for i in range(1, 13)])) == []
    problems = vs(spec_with(*[tile(i) for i in range(1, 14)]))
    assert_plain(problems)


# -- extra keys at every level ---------------------------------------------------------------------

def _poke(path):
    def run(spec):
        node = spec
        for step in path:
            node = node[step]
        node["bogus"] = "x"
        return spec
    return run


EXTRA_KEY_LEVELS = {
    "root": ([], ""),
    "period_object": (["period"], "period"),
    "tile": (["tiles", 0], "tiles[0]"),
    "source": (["tiles", 0, "source"], "tiles[0].source"),
    "query": (["tiles", 0, "source", "spec"], "tiles[0].source.spec"),
    "filter": (["tiles", 0, "source", "spec", "filters", 0], "tiles[0].source.spec.filters[0]"),
    "group_object": (["tiles", 0, "source", "spec", "group_by", 0], "tiles[0].source.spec.group_by[0]"),
    "aggregate": (["tiles", 0, "source", "spec", "aggregates", 0], "tiles[0].source.spec.aggregates[0]"),
    "sort": (["tiles", 0, "source", "spec", "sort", 0], "tiles[0].source.spec.sort[0]"),
}


@pytest.mark.parametrize("level", sorted(EXTRA_KEY_LEVELS))
def test_extra_key_refused_at_every_level(level):
    path, prefix = EXTRA_KEY_LEVELS[level]
    spec = _poke(path)(rich_spec())
    problems = vs(spec)
    assert_plain(problems)
    if prefix:
        assert any(p["path"].startswith(prefix) for p in problems), problems


def test_wrong_version_refused():
    spec = f1_spec()
    spec["version"] = 2
    assert_plain(vs(spec))


# -- forbidden sequences in any string -------------------------------------------------------------

SEQUENCES = ["<", ">", "://", ";", "--", "/*", "\x07", "\x00"]


def _title(spec, text):
    spec["title"] = text


def _tile_title(spec, text):
    spec["tiles"][0]["title"] = text


def _filter_value(spec, text):
    spec["tiles"][0]["source"]["spec"]["filters"] = [{"field": "customer_name", "op": "eq", "value": text}]


def _filter_list_value(spec, text):
    spec["tiles"][0]["source"]["spec"]["filters"] = [{"field": "customer_name", "op": "in", "value": ["fine", text]}]


def _entity(spec, text):
    spec["tiles"][0]["source"]["spec"]["entity"] = text


PLACES = {"title": _title, "tile_title": _tile_title, "filter_value": _filter_value,
          "filter_list_value": _filter_list_value, "entity": _entity}


@pytest.mark.parametrize("place", sorted(PLACES))
@pytest.mark.parametrize("seq", SEQUENCES, ids=lambda s: repr(s))
def test_forbidden_sequence_refused_with_plain_reason(place, seq):
    spec = spec_with(tile(1, "number"))
    text = f"ab{seq}cd" if place != "entity" else f"billing_document{seq}"
    PLACES[place](spec, text)
    problems = vs(spec)
    assert_plain(problems)
    assert any(p["reason"] == FORBIDDEN for p in problems), problems


def test_f10_style_entity_and_url_and_html_and_extra_key_all_refused():
    for mutate in (lambda s: _entity(s, "x; drop table"),
                   lambda s: _tile_title(s, "see http://example.invalid/x"),
                   lambda s: _tile_title(s, "<b>bold</b>"),
                   lambda s: s["tiles"][0].update({"unknown": 1})):
        spec = spec_with(tile(1))
        mutate(spec)
        assert_plain(vs(spec))


def test_ordinary_text_with_dash_and_quotes_is_not_refused():
    spec = spec_with(tile(1), title="Sales - this year (RM) it's fine")
    spec["tiles"][0]["title"] = "Top 10, by region & month"
    assert vs(spec) == []


# -- caps ------------------------------------------------------------------------------------------

def test_spec_over_32768_bytes_refused():
    def big_filter(n):
        return [{"field": "customer_name", "op": "in", "value": [("x%d" % i).ljust(200, "y") for i in range(100)]}
                for _ in range(n)]

    ok = spec_with(tile(1, "number", filters=big_filter(1)))
    assert len(json.dumps(ok, separators=(",", ":")).encode()) < 32768
    assert vs(ok) == []
    big = spec_with(tile(1, "number", filters=big_filter(2)))
    assert len(json.dumps(big, separators=(",", ":")).encode()) > 32768
    assert_plain(vs(big))


def test_title_length_caps():
    assert vs(spec_with(tile(1), title="a" * 80)) == []
    assert_plain(vs(spec_with(tile(1), title="a" * 81)))
    assert_plain(vs(spec_with(tile(1), title="")))
    assert_plain(vs(spec_with(tile(1), title="   ")))
    long_tile = spec_with(tile(1))
    long_tile["tiles"][0]["title"] = "b" * 81
    assert_plain(vs(long_tile))
    empty_tile = spec_with(tile(1))
    empty_tile["tiles"][0]["title"] = ""
    assert_plain(vs(empty_tile))


@pytest.mark.parametrize("bad_id", ["x1", "T1", "t", "t1234", "1", "t-1", "t1 "])
def test_bad_tile_id_refused(bad_id):
    t = tile(1)
    t["id"] = bad_id
    assert_plain(vs(spec_with(t)))


def test_duplicate_tile_ids_refused():
    problems = vs(spec_with(tile(1), tile(1)))
    assert_plain(problems)


# -- not available in slice 1 ----------------------------------------------------------------------

@pytest.mark.parametrize("show", ["pivot", "widget"])
def test_pivot_and_widget_show_refused_with_not_yet(show):
    t = tile(1, "table")
    t["show"] = show
    problems = vs(spec_with(t))
    assert any(p["reason"] == NOT_YET for p in problems), problems
    assert_plain(problems)


@pytest.mark.parametrize("kind", ["report", "widget"])
def test_report_and_widget_source_kinds_refused_with_not_yet(kind):
    t = tile(1, "table")
    t["source"]["kind"] = kind
    problems = vs(spec_with(t))
    assert any(p["reason"] == NOT_YET for p in problems), problems


def test_unknown_show_and_kind_and_op_and_fn_refused_plainly():
    t = tile(1, "table")
    t["show"] = "pie"
    assert_plain(vs(spec_with(t)))
    t = tile(1, "table")
    t["source"]["kind"] = "sql"
    assert_plain(vs(spec_with(t)))
    t = tile(1, "number", filters=[{"field": "customer_name", "op": "regex", "value": "a"}])
    assert_plain(vs(spec_with(t)))
    t = tile(1, "number", aggregates=[{"fn": "median", "field": "sales_amount"}])
    assert_plain(vs(spec_with(t)))


def test_bad_period_refused_plainly():
    assert_plain(vs(spec_with(tile(1), period="next_week")))
    assert_plain(vs(spec_with(tile(1), period={"from": "2026-13-45", "to": "2026-01-01"})))
    assert_plain(vs(spec_with(tile(1), period={"from": "2026-01-01"})))


def test_missing_required_parts_use_plain_words():
    for key in ("title", "period", "tiles", "version"):
        spec = f1_spec()
        del spec[key]
        assert_plain(vs(spec))
    t = tile(1)
    del t["source"]["spec"]["entity"]
    assert_plain(vs(spec_with(t)))
    t = tile(1)
    del t["title"]
    assert_plain(vs(spec_with(t)))


# -- shape rules -----------------------------------------------------------------------------------

def test_number_shape_rules():
    two = tile(1, "number", aggregates=[{"fn": "sum", "field": "sales_amount"}, {"fn": "count"}])
    assert_plain(vs(spec_with(two)))
    grouped = tile(1, "number", group_by=["customer_name"])
    assert_plain(vs(spec_with(grouped)))
    none = tile(1, "number")
    del none["source"]["spec"]["aggregates"]
    assert_plain(vs(spec_with(none)))


@pytest.mark.parametrize("show", ["line", "bar"])
def test_line_and_bar_shape_rules(show):
    assert vs(spec_with(tile(1, show))) == []
    no_group = tile(1, show)
    del no_group["source"]["spec"]["group_by"]
    assert_plain(vs(spec_with(no_group)))
    no_agg = tile(1, show)
    del no_agg["source"]["spec"]["aggregates"]
    assert_plain(vs(spec_with(no_agg)))


def test_table_shape_rules():
    assert vs(spec_with(tile(1, "table"))) == []  # rows
    grouped = tile(1, "table")
    del grouped["source"]["spec"]["fields"]
    grouped["source"]["spec"]["group_by"] = ["customer_name"]
    grouped["source"]["spec"]["aggregates"] = [{"fn": "sum", "field": "sales_amount"}]
    assert vs(spec_with(grouped)) == []
    neither = tile(1, "table")
    del neither["source"]["spec"]["fields"]
    assert_plain(vs(spec_with(neither)))


def test_query_caps_refused():
    many_filters = tile(1, "number", filters=[{"field": "customer_name", "op": "is_null"}] * 21)
    assert_plain(vs(spec_with(many_filters)))
    bad_limit = tile(1, "table", limit=201)
    assert_plain(vs(spec_with(bad_limit)))
    zero_limit = tile(1, "table", limit=0)
    assert_plain(vs(spec_with(zero_limit)))
    too_many_fields = tile(1, "table", fields=[f"f{i}" for i in range(9)])
    assert_plain(vs(spec_with(too_many_fields)))


# -- against the catalogue -------------------------------------------------------------------------

def test_unknown_entity_refused():
    spec = spec_with(tile(1, "number", entity="payroll"))
    problems = vc(spec)
    assert_plain(problems)
    assert any("entity" in p["path"] for p in problems), problems


@pytest.mark.parametrize("where", ["filter", "group_by", "group_by_object", "aggregate", "fields"])
def test_unknown_field_refused_in_every_slot(where):
    if where == "filter":
        t = tile(1, "number", filters=[{"field": "salary", "op": "gt", "value": 1}])
    elif where == "group_by":
        t = tile(1, "bar", group_by=["salary"])
    elif where == "group_by_object":
        t = tile(1, "bar", group_by=[{"field": "salary", "bucket": "month"}])
    elif where == "aggregate":
        t = tile(1, "number", aggregates=[{"fn": "sum", "field": "salary"}])
    else:
        t = tile(1, "table", fields=["doc_date", "salary"])
    assert_plain(vc(spec_with(t)))


def test_relation_path_one_hop():
    ok_fields = tile(1, "table", fields=["doc_date", "customer.name"])
    assert vc(spec_with(ok_fields)) == []
    ok_filter = tile(1, "number", filters=[{"field": "customer.name", "op": "eq", "value": "Fake Customer One"}])
    assert vc(spec_with(ok_filter)) == []
    ok_group = tile(1, "bar", group_by=["customer.name"])
    assert vc(spec_with(ok_group)) == []
    assert_plain(vc(spec_with(tile(1, "table", fields=["customer.nope"]))))
    assert_plain(vc(spec_with(tile(1, "number", filters=[{"field": "customer.nope", "op": "eq", "value": "x"}]))))
    assert_plain(vc(spec_with(tile(1, "table", fields=["nothing.name"]))))


def test_show_not_in_entity_show_list_refused():
    cat = catalogue()
    catalogue_entity(cat, "billing_document")["show"] = ["number", "table"]
    problems = vc(spec_with(tile(1, "bar")), cat)
    assert_plain(problems)
    assert vc(spec_with(tile(1, "number")), cat) == []


def test_customer_entity_does_not_offer_line():
    t = tile(1, "line", entity="customer", group_by=[{"field": "created_on", "bucket": "month"}],
             aggregates=[{"fn": "count"}])
    assert_plain(vc(spec_with(t)))


def test_totals_not_allowed_means_table_only():
    # support_ticket: totals_allowed false.
    ok = tile(1, "table", entity="support_ticket", fields=["subject", "opened_on"])
    assert vc(spec_with(ok)) == []
    for show in ("number", "bar", "line"):
        t = tile(1, show, entity="support_ticket")
        t["source"]["spec"].pop("group_by", None)
        t["source"]["spec"]["aggregates"] = [{"fn": "count"}]
        if show != "number":
            t["source"]["spec"]["group_by"] = ["subject"]
        assert_plain(vc(spec_with(t)))
    # even if the (inconsistent) show list still lists a chart type
    cat = catalogue()
    ent = catalogue_entity(cat, "support_ticket")
    ent["show"] = ["number", "bar", "table"]
    t = tile(1, "bar", entity="support_ticket", group_by=["subject"], aggregates=[{"fn": "count"}])
    assert_plain(vc(spec_with(t), cat))


def test_catalogue_problem_paths_point_at_the_tile():
    spec = spec_with(tile(1), tile(2, "number", entity="payroll"))
    problems = vc(spec)
    assert any(p["path"].startswith("tiles[1]") for p in problems), problems
