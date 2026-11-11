"""Plan 63 (RED): the acting person on every write, AC-63-20..23.

Headers ``X-Acting-User-Id`` (1..64 printable ASCII) and ``X-Acting-User-Name`` (UTF-8,
percent-encoded, 1..128 characters after decoding, control characters removed) are read next to
``X-Request-ID`` on every write route and stored on every ``ac_api_call_log`` row and every
``ac_write_action`` row the request causes (``request_id`` too on the action row). A missing or
invalid header stores NULL and never refuses. Runner / system calls store NULL.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from modules.autocount.models import AcApiCallLog, AcWriteAction
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code, create_body
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line, _service_cls
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

ID_HEADER = "X-Acting-User-Id"
NAME_HEADER = "X-Acting-User-Name"
CJK = "陈大文"
CJK_ENC = "%E9%99%88%E5%A4%A7%E6%96%87"


def _cl():
    from modules.autocount.write_back import call_log

    return call_log


# ------------------------------------------------------------------ the parser

def test_ac_63_20_header_names_are_exported():
    cl = _cl()
    assert cl.ACTING_USER_ID_HEADER == "X-Acting-User-Id"
    assert cl.ACTING_USER_NAME_HEADER == "X-Acting-User-Name"


def test_ac_63_20_valid_id_and_plain_name():
    assert _cl().person_of("u-123", "Alice Tan") == ("u-123", "Alice Tan")


def test_ac_63_21_absent_headers_are_none():
    cl = _cl()
    assert cl.person_of(None, None) == (None, None)
    assert cl.person_of("", "") == (None, None)


@pytest.mark.parametrize("value,ok", [
    ("a", True), ("x" * 64, True), ("x" * 65, False), ("a\x01b", False), ("a\x7fb", False),
    ("a\nb", False), ("a\tb", False), ("café", False), ("user:42/b", True),
])
def test_ac_63_20_id_rule_is_1_to_64_printable_ascii(value, ok):
    got = _cl().person_of(value, None)[0]
    assert got == (value if ok else None)


def test_ac_63_21_a_non_ascii_name_is_stored_decoded():
    assert _cl().person_of("u1", CJK_ENC) == ("u1", CJK)


@pytest.mark.parametrize("raw,want", [
    ("%FF%FE", None),                       # not UTF-8
    ("%E9%99", None),                       # truncated UTF-8 sequence
    ("A%00B%0AC%1FD", "ABCD"),              # control characters removed
    ("%00%0A%1F", None),                    # nothing left after removal
    ("%41" * 128, "A" * 128),               # 128 decoded chars: allowed
    ("%41" * 129, None),                    # 129 decoded chars: refused
    ("A" * 129, None),
    ("Mary%20Ann", "Mary Ann"),
])
def test_ac_63_20_name_rule(raw, want):
    assert _cl().person_of(None, raw)[1] == want


def test_ac_63_21_a_bad_id_does_not_discard_a_good_name_and_the_reverse():
    cl = _cl()
    assert cl.person_of("x" * 65, "Bob") == (None, "Bob")
    assert cl.person_of("u-9", "%FF") == ("u-9", None)


def test_ac_63_22_call_context_defaults_to_no_person():
    ctx = _cl().CallContext(tenant_id="t", company_id="c")
    assert ctx.acting_user_id is None and ctx.acting_user_name is None


def test_ac_63_20_the_log_has_no_header_parameter_so_a_key_can_never_reach_it():
    import inspect

    params = set(inspect.signature(_cl().CallLog.record).parameters)
    assert not any("header" in p for p in params)


# ------------------------------------------------------------------ models

def test_ac_63_23_models_carry_the_new_nullable_columns():
    for model, names in ((AcApiCallLog, ("acting_user_id", "acting_user_name")),
                         (AcWriteAction, ("request_id", "acting_user_id", "acting_user_name"))):
        for name in names:
            col = model.__table__.columns.get(name)
            assert col is not None, f"{model.__name__}.{name} is missing"
            assert col.nullable is True


def test_ac_63_23_migration_0045_exists_with_the_planned_columns():
    root = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
    files = list(root.glob("0045_autocount_call_person*.py"))
    assert len(files) == 1, files
    text = files[0].read_text()
    assert re.search(r"revision\s*(?::\s*str\s*)?=\s*[\"']0045_autocount_call_person[\"']", text)
    assert "0044_autocount_api_call_log" in text
    for name in ("acting_user_id", "acting_user_name", "request_id", "ac_write_action", "ac_api_call_log"):
        assert name in text


def test_ac_63_23_there_is_a_single_module_migration_head():
    root = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
    revisions, downs = set(), set()
    for path in root.glob("*.py"):
        text = path.read_text()
        m = re.search(r"^revision\s*(?::\s*str\s*)?=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
        d = re.search(r"^down_revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
        if m:
            revisions.add(m.group(1))
        if d:
            downs.add(d.group(1))
    heads = revisions - downs
    assert heads == {"0045_autocount_call_person"}, heads


# ------------------------------------------------------------------ rig

@pytest.fixture
def gw(h, db):
    h.delete_on()
    return Gw(h, db)


@pytest.fixture
def world(gw):
    return World(gw.h)


def _call_rows(h) -> List[AcApiCallLog]:
    s = h.session_factory()
    try:
        return s.query(AcApiCallLog).order_by(AcApiCallLog.created_at).all()
    finally:
        s.close()


def _actions(h) -> List[AcWriteAction]:
    h.db.expire_all()
    return h.db.query(AcWriteAction).order_by(AcWriteAction.created_at).all()


def _edit(client, gw, doc_key, idem, headers=None, ref="x"):
    return client.patch(f"{PREFIX}/documents/sales-orders/{doc_key}", headers=gw.hdr(idem, **(headers or {})),
                        json={"companyCode": "SRT", "header": {"ref": ref}})


# ------------------------------------------------------------------ AC-63-20 rows carry the person

def test_ac_63_20_a_primitive_write_stamps_every_call_row_and_the_action(client, gw):
    h = gw.h
    h.seed_doc("SO", 7201, [_line("A", 10, 5.0)])
    r = _edit(client, gw, 7201, "idem-p1", {ID_HEADER: "u-123", NAME_HEADER: CJK_ENC, "X-Request-ID": "req-abc"})
    assert r.status_code == 200, r.text
    rows = _call_rows(h)
    assert rows and {x.method for x in rows} >= {"PUT", "GET"}
    for row in rows:
        assert (row.acting_user_id, row.acting_user_name) == ("u-123", CJK)
        assert row.request_id == "req-abc"
    actions = _actions(h)
    assert len(actions) == 1
    assert (actions[0].acting_user_id, actions[0].acting_user_name) == ("u-123", CJK)
    assert actions[0].request_id == "req-abc"


def test_ac_63_20_request_id_falls_back_to_the_idempotency_key_on_the_action_row(client, gw):
    h = gw.h
    h.seed_doc("SO", 7202, [_line("A", 10, 5.0)])
    assert _edit(client, gw, 7202, "idem-fallback").status_code == 200
    assert _actions(h)[0].request_id == "idem-fallback"


def test_ac_63_20_create_and_cancel_routes_stamp_the_person_too(client, gw):
    h = gw.h
    hdr = {ID_HEADER: "u-7", NAME_HEADER: "Sam", "X-Request-ID": "req-multi"}
    r = client.post(f"{PREFIX}/documents/quotations", headers=gw.hdr("idem-c1", **hdr), json=create_body("QT"))
    assert r.status_code == 200, r.text
    h.seed_doc("SO", 7203, [_line("A", 10, 5.0)])
    r = client.post(f"{PREFIX}/documents/sales-orders/7203/cancel", headers=gw.hdr("idem-c2", **hdr),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert {x.method for x in _call_rows(h)} >= {"POST", "DELETE"}
    for row in _call_rows(h):
        assert (row.acting_user_id, row.acting_user_name, row.request_id) == ("u-7", "Sam", "req-multi")
    actions = _actions(h)
    assert len(actions) == 2
    assert all((a.acting_user_id, a.acting_user_name, a.request_id) == ("u-7", "Sam", "req-multi") for a in actions)


def test_ac_63_20_an_operation_route_stamps_every_action_row_it_causes(client, gw, world):
    h = gw.h
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002,
            "soDtlKey": world.so_b}
    r = client.post(f"{PREFIX}/po-links/relink", json=body,
                    headers=gw.hdr("idem-op", **{ID_HEADER: "u-55", NAME_HEADER: "Op%20Person",
                                                 "X-Request-ID": "req-op"}))
    assert r.status_code == 200, r.text
    actions = _actions(h)
    assert len(actions) >= 1
    for a in actions:
        assert (a.acting_user_id, a.acting_user_name, a.request_id) == ("u-55", "Op Person", "req-op")
    rows = _call_rows(h)
    assert rows and all((x.acting_user_id, x.acting_user_name) == ("u-55", "Op Person") for x in rows)


def test_ac_63_20_the_plan_55_link_routes_stamp_the_person_too(client, gw, world):
    h = gw.h
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    r = client.post(f"{PREFIX}/po-links/unlink", json=body,
                    headers=gw.hdr("idem-unlink", **{ID_HEADER: "u-56", NAME_HEADER: "Link%20User",
                                                     "X-Request-ID": "req-unlink"}))
    assert r.status_code == 200, r.text
    rows = _call_rows(h)
    assert rows and all((x.acting_user_id, x.acting_user_name, x.request_id) == ("u-56", "Link User", "req-unlink")
                        for x in rows)
    actions = _actions(h)
    assert actions and all((a.acting_user_id, a.acting_user_name, a.request_id) == ("u-56", "Link User", "req-unlink")
                           for a in actions)


# ------------------------------------------------------------------ AC-63-21 invalid or missing = NULL, never 4xx

@pytest.mark.parametrize("headers", [
    {},
    {ID_HEADER: "x" * 65},
    {NAME_HEADER: "%FF%FE"},
    {NAME_HEADER: "A" * 129},
    {ID_HEADER: "x" * 65, NAME_HEADER: "%E9%99"},
    {ID_HEADER: "café"},
])
def test_ac_63_21_missing_or_invalid_headers_store_null_and_the_write_runs(client, gw, headers):
    h = gw.h
    h.seed_doc("SO", 7210, [_line("A", 10, 5.0)])
    r = _edit(client, gw, 7210, "idem-bad", headers)
    assert r.status_code == 200, r.text
    rows = _call_rows(h)
    assert rows
    expect_id = None
    expect_name = None
    assert all((x.acting_user_id, x.acting_user_name) == (expect_id, expect_name) for x in rows)
    a = _actions(h)[0]
    assert (a.acting_user_id, a.acting_user_name) == (expect_id, expect_name)
    assert [c.method for c in h.vendor.writes()] == ["PUT"]


def test_ac_63_21_control_valid_headers_do_store_so_the_null_cases_are_not_vacuous(client, gw):
    h = gw.h
    h.seed_doc("SO", 7211, [_line("A", 10, 5.0)])
    assert _edit(client, gw, 7211, "idem-ok", {ID_HEADER: "u-1", NAME_HEADER: "Ann"}).status_code == 200
    assert {(x.acting_user_id, x.acting_user_name) for x in _call_rows(h)} == {("u-1", "Ann")}


def test_ac_63_21_control_characters_in_a_name_are_removed_not_refused(client, gw):
    h = gw.h
    h.seed_doc("SO", 7212, [_line("A", 10, 5.0)])
    r = _edit(client, gw, 7212, "idem-ctl", {NAME_HEADER: "A%00B%0AC"})
    assert r.status_code == 200
    assert {x.acting_user_name for x in _call_rows(h)} == {"ABC"}


def test_ac_63_21_a_bad_name_with_a_good_id_keeps_the_id(client, gw):
    h = gw.h
    h.seed_doc("SO", 7213, [_line("A", 10, 5.0)])
    assert _edit(client, gw, 7213, "idem-mix", {ID_HEADER: "u-2", NAME_HEADER: "%FF"}).status_code == 200
    assert {(x.acting_user_id, x.acting_user_name) for x in _call_rows(h)} == {("u-2", None)}


def test_ac_63_21_a_refused_write_still_records_the_person_on_its_action_row(client, gw):
    h = gw.h
    r = _edit(client, gw, 99999, "idem-unknown", {ID_HEADER: "u-3", NAME_HEADER: "Cy", "X-Request-ID": "req-r"})
    assert r.status_code != 200
    actions = _actions(h)
    assert actions and (actions[0].acting_user_id, actions[0].acting_user_name, actions[0].request_id) == (
        "u-3", "Cy", "req-r")


# ------------------------------------------------------------------ AC-63-22 runner and system

def test_ac_63_22_a_service_call_without_the_headers_stores_null_person(h):
    h.seed_doc("SO", 7220, [_line("A", 10, 5.0)])
    res = h.edit("SO", 7220, {"Remark1": "hello"})
    assert res.outcome == "done", res.error_code
    rows = _call_rows(h)
    assert rows and all(x.acting_user_id is None and x.acting_user_name is None for x in rows)
    a = h.action(res)
    assert a.acting_user_id is None and a.acting_user_name is None


def test_ac_63_22_the_runner_actor_stores_null_person(h):
    h.seed_doc("SO", 7221, [_line("A", 10, 5.0)])
    svc = _service_cls()(h.db, actor="runner", **h.factories())
    res = svc.edit_doc(**h.args("SO", doc_key=7221, header_changes={"Remark1": "hi"}, line_changes=[]))
    assert res.outcome == "done", res.error_code
    rows = _call_rows(h)
    assert rows and all(x.actor == "runner" and x.acting_user_id is None and x.acting_user_name is None
                        for x in rows)
    a = h.action(res)
    assert a.acting_user_id is None and a.acting_user_name is None


def test_ac_63_22_existing_rows_keep_null_columns_default(h):
    # rows written before the migration (or by code that never learns a person) have no person
    s = h.session_factory()
    try:
        from datetime import datetime, timezone

        row = AcApiCallLog(tenant_id="t", company_id="c", created_at=datetime.now(timezone.utc), actor="system",
                           method="GET", path="/x", outcome="ok")
        s.add(row)
        s.commit()
        assert row.acting_user_id is None and row.acting_user_name is None
    finally:
        s.close()
