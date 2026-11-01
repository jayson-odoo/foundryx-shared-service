"""Plan 42 review round: red tests for the token proof, reply parsing, scopes
and app checks, the replace throttle, schedule, overlap, status kept on
restore, and list/export filters. Fake tokens and numbers only; no network."""
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_token_health import (
    DISPLAY,
    PN,
    TOKEN_NEW,
    TOKEN_OLD,
    _auth,
    _graph_adapter,
    _provision_tenant,
    _read,
    _replace,
    _run_check,
    _spy_email,
    _stub,
    _user,
    _wa_channel,
)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    def boom(self, *a, **k):
        raise AssertionError("a real network call was attempted")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)


def _recorder(status=200, body=None):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else {})

    return seen, handler


# ── 1. check_token proves the number ─────────────────────────────────────────
def test_check_sends_fields_id(monkeypatch):
    seen, handler = _recorder(200, {"id": PN})
    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.check_token({"access_token": TOKEN_NEW}, PN) == "ok"
    assert seen[0].url.params.get("fields") == "id"


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"id": PN}, "ok"),
        ({"id": "pn-someone-else"}, "unknown"),
        ({"id": None}, "unknown"),
        ({}, "unknown"),
        ({"error": {"code": 190, "message": "m"}}, "dead"),
        ({"error": {"code": 4, "message": "m"}}, "unknown"),
    ],
    ids=["same id", "other id", "null id", "missing id", "200 with 190", "200 with 4"],
)
def test_check_200_body_decides(monkeypatch, body, expected):
    _, handler = _recorder(200, body)
    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.check_token({"access_token": TOKEN_NEW}, PN) == expected


@pytest.mark.parametrize(
    "status,body,expected",
    [(200, {"id": PN}, "ok"), (400, {"error": {"code": 190}}, "dead"), (500, {}, "unknown")],
)
def test_check_without_app_credentials_still_calls_graph(monkeypatch, status, body, expected):
    seen, handler = _recorder(status, body)
    adapter = _graph_adapter(monkeypatch, handler, app_configured=False)
    assert adapter.check_token({"access_token": TOKEN_NEW}, PN) == expected
    assert len(seen) == 1


def test_check_dev_credentials_make_no_call(monkeypatch):
    seen, handler = _recorder(200, {"id": PN})
    adapter = _graph_adapter(monkeypatch, handler, app_configured=False)
    adapter.check_token({"dev": True}, PN)
    assert seen == []


# ── 2. subscribe_app_checked reads the answer ────────────────────────────────
@pytest.mark.parametrize(
    "status,body,expected",
    [(200, {"success": True}, True), (200, {"success": False}, False), (400, {"error": {"code": 100}}, False)],
)
def test_subscribe_checked_reads_success(monkeypatch, status, body, expected):
    _, handler = _recorder(status, body)
    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.subscribe_app_checked({"access_token": TOKEN_NEW}, "waba-th-1") is expected


# ── 3. token_details ─────────────────────────────────────────────────────────
TS = 1803000000


def _details_adapter(monkeypatch, data, status=200):
    seen, handler = _recorder(status, {"data": data})
    return seen, _graph_adapter(monkeypatch, handler)


def test_token_details_returns_expiry_scopes_and_app(monkeypatch):
    seen, adapter = _details_adapter(
        monkeypatch, {"expires_at": TS, "scopes": ["whatsapp_business_messaging"], "app_id": "test-app-id"}
    )
    assert adapter.token_details(TOKEN_NEW) == {
        "expires_at": datetime.fromtimestamp(TS, tz=timezone.utc),
        "scopes": ["whatsapp_business_messaging"],
        "app_id": "test-app-id",
    }
    req = seen[0]
    assert "test-app-secret" in req.headers.get("authorization", "")
    assert "test-app-secret" not in str(req.url)
    assert req.url.params.get("input_token") == TOKEN_NEW


def test_token_details_zero_expiry_means_none(monkeypatch):
    _, adapter = _details_adapter(monkeypatch, {"expires_at": 0, "scopes": [], "app_id": "a"})
    assert adapter.token_details(TOKEN_NEW)["expires_at"] is None


def test_token_details_missing_fields_are_none(monkeypatch):
    _, adapter = _details_adapter(monkeypatch, {"expires_at": TS})
    out = adapter.token_details(TOKEN_NEW)
    assert out["scopes"] is None and out["app_id"] is None


@pytest.mark.parametrize("status", [400, 500])
def test_token_details_unreadable_is_none(monkeypatch, status):
    _, adapter = _details_adapter(monkeypatch, {"error": {"code": 190}}, status=status)
    assert adapter.token_details(TOKEN_NEW) is None


# ── 4. logging ───────────────────────────────────────────────────────────────
def test_http_client_logger_is_quiet_and_calls_leave_no_secret(monkeypatch, caplog):
    import app.main  # noqa: F401

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    caplog.set_level(logging.INFO)
    _, handler = _recorder(200, {"id": PN, "success": True, "data": {"expires_at": TS}})
    adapter = _graph_adapter(monkeypatch, handler)
    creds = {"access_token": TOKEN_NEW}
    adapter.check_token(creds, PN)
    adapter.subscribe_app_checked(creds, "waba-th-1")
    if hasattr(adapter, "token_details"):
        adapter.token_details(TOKEN_NEW)
    assert TOKEN_NEW not in caplog.text
    assert "test-app-secret" not in caplog.text


# ── 5. scopes ────────────────────────────────────────────────────────────────
def _channel_and_headers(session_factory, client, **kw):
    return _wa_channel(session_factory, status_key="ERROR", **kw), _auth(client)


@pytest.mark.parametrize(
    "scopes,expected",
    [(["business_management"], 422), (None, 200), (["whatsapp_business_messaging", "x"], 200)],
    ids=["missing the scope", "unreadable", "has the scope"],
)
def test_replace_requires_messaging_scope_when_readable(client, session_factory, monkeypatch, scopes, expected):
    _stub(monkeypatch, check="ok", scopes=scopes)
    cid, h = _channel_and_headers(session_factory, client)
    before = _read(session_factory, cid)
    res = _replace(client, h, cid)
    assert res.status_code == expected, res.text
    after = _read(session_factory, cid)
    if expected == 422:
        assert (after[0], after[2]) == (before[0], before[2])
    else:
        assert after[3]["access_token"] == TOKEN_NEW


# ── 6. app id ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "details_app,called,subscribed",
    [("other-app", False, False), ("test-app-id", True, True), (None, False, False)],
    ids=["different app", "same app", "unreadable"],
)
def test_replace_renews_webhook_only_for_this_app(client, session_factory, monkeypatch, details_app, called, subscribed):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    st = _stub(monkeypatch, check="ok", app_id=details_app, subscribe=True)
    cid, h = _channel_and_headers(session_factory, client)
    res = _replace(client, h, cid)
    assert res.status_code == 200, res.text
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW
    assert bool(st.subscribe_calls) is called
    assert res.json()["subscribed"] is subscribed


@pytest.mark.parametrize(
    "details",
    [None, RuntimeError("debug refused")],
    ids=["details unreadable", "details raises"],
)
def test_replace_skips_renewal_when_token_details_cannot_be_read(client, session_factory, monkeypatch, details):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    st = _stub(monkeypatch, check="ok", details=details, subscribe=True)
    cid, h = _channel_and_headers(session_factory, client)
    res = _replace(client, h, cid)
    assert res.status_code == 200, res.text
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW
    assert st.subscribe_calls == []
    assert res.json()["subscribed"] is False


# ── 7. no phone number ───────────────────────────────────────────────────────
def test_replace_without_phone_number_id_is_422_and_makes_no_call(client, session_factory, monkeypatch):
    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key="ERROR", pn=None)
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 422
    assert st.check_calls == []
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_OLD
    # control: the same setup with a number is saved
    other = _wa_channel(session_factory, name="with number", status_key="ERROR", pn="pn-rv-7")
    assert _replace(client, _auth(client), other).status_code == 200


# ── 8. dev-flagged channel ───────────────────────────────────────────────────
def test_replace_on_dev_channel_really_checks_and_drops_the_flag(client, session_factory, monkeypatch):
    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key="ERROR", creds={"dev": True})
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    assert len(st.check_calls) == 1
    assert "dev" not in st.check_calls[0][0]
    creds = _read(session_factory, cid)[3]
    assert "dev" not in creds and creds["access_token"] == TOKEN_NEW


# ── 9. throttle ──────────────────────────────────────────────────────────────
def test_replace_is_throttled_per_channel_and_refusals_count(client, session_factory, monkeypatch):
    st = _stub(monkeypatch, check="dead")
    busy = _wa_channel(session_factory, name="busy", pn="pn-th-busy", status_key="ERROR")
    quiet = _wa_channel(session_factory, name="quiet", pn="pn-th-quiet", status_key="ERROR")
    h = _auth(client)
    for _ in range(10):
        assert _replace(client, h, busy).status_code == 422
    calls_before = len(st.check_calls)
    assert calls_before == 10
    res = _replace(client, h, busy)
    assert res.status_code == 429, res.text
    assert len(st.check_calls) == calls_before, "a throttled attempt makes no Graph call"
    st.check = "ok"
    assert _replace(client, h, quiet).status_code == 200  # another channel is unaffected


# ── 10. schedule ─────────────────────────────────────────────────────────────
def test_beat_entry_is_a_wall_clock_crontab():
    from celery.schedules import crontab

    from app.workflow_engine.worker import celery_app

    entries = [e for e in celery_app.conf.beat_schedule.values() if "token" in str(e.get("task", ""))]
    assert entries
    assert entries[0]["schedule"] == crontab(minute=0, hour="*/6")


# ── 11. overlapping checks ───────────────────────────────────────────────────
@pytest.mark.parametrize("concurrent,expected_mails", [(True, 0), (False, 1)])
def test_overlapping_dead_checks_send_one_email_total(session_factory, monkeypatch, concurrent, expected_mails):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services import statuses

    calls = _spy_email(monkeypatch)
    cid = _wa_channel(session_factory)

    def dead(credentials, phone_number_id):
        if concurrent:
            other = session_factory()
            ch = other.query(Channel).filter(Channel.id == cid).first()
            ch.status_id = statuses.status_id_for(other, ch.tenant_id, "CHANNEL", "ERROR")
            other.commit()
            other.close()
        return "dead"

    _stub(monkeypatch, check=dead)
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ERROR"
    assert len(calls) == expected_mails


# ── 12. disconnect then restore keeps ERROR ──────────────────────────────────
def test_restore_keeps_error_and_next_dead_check_sends_no_email(client, session_factory, monkeypatch):
    calls = _spy_email(monkeypatch)
    _stub(monkeypatch, check="dead")
    cid = _wa_channel(session_factory, status_key="ERROR")
    h = _auth(client)
    assert client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [cid]}).status_code == 204
    assert client.post("/omnichannel/channels/restore", headers=h, json={"ids": [cid]}).status_code == 204
    key, active, _, _ = _read(session_factory, cid)
    assert (key, active) == ("ERROR", True)
    _run_check(session_factory, cid)
    assert calls == []


def test_restore_still_activates_a_normal_channel_control(client, session_factory):
    cid = _wa_channel(session_factory, status_key="ACTIVE")
    h = _auth(client)
    client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [cid]})
    client.post("/omnichannel/channels/restore", headers=h, json={"ids": [cid]})
    assert _read(session_factory, cid)[:2] == ("ACTIVE", True)


# ── 13..15 filters ───────────────────────────────────────────────────────────
def _cond(field, op, value):
    return {"kind": "condition", "field": field, "operator": op, "value": value}


def _grp(*rules):
    return json.dumps({"kind": "group", "combinator": "and", "rules": list(rules)})


@pytest.fixture
def seeded(session_factory):
    def mk(name, pn, status, ctype="WHATSAPP", display=DISPLAY):
        cid = _wa_channel(session_factory, name=name, pn=pn, status_key=status, channel_type=ctype)
        if ctype == "WHATSAPP" and display != DISPLAY:
            from modules.omnichannel.models import Channel

            db = session_factory()
            db.query(Channel).filter(Channel.id == cid).update({Channel.display_phone_number: display})
            db.commit()
            db.close()
        return cid

    mk("Alpha Line", "pn-fl-1", "ERROR")
    mk("Beta Line", "pn-fl-2", "ERROR", display="+60 11-111 0077")
    mk("Gamma Page", "pn-fl-3", "ERROR", ctype="FACEBOOK")
    mk("Alpha Two", "pn-fl-4", "ACTIVE")
    return session_factory


FILTER_CASES = [
    ([_cond("status", "eq", "ERROR"), _cond("name", "contains", "Alpha")], {"Alpha Line"}),
    ([_cond("status", "in", ["ERROR"]), _cond("displayPhoneNumber", "contains", "0077")], {"Beta Line"}),
    ([_cond("status", "eq", "ERROR"), _cond("channelType", "in", ["FACEBOOK"])], {"Gamma Page"}),
    ([_cond("status", "eq", "ERROR"), _cond("channelType", "eq", "WHATSAPP")], {"Alpha Line", "Beta Line"}),
    ([_cond("name", "eq", "Alpha Two")], {"Alpha Two"}),
    ([_cond("name", "neq", "Alpha Two"), _cond("status", "in", ["ERROR"])], {"Alpha Line", "Beta Line", "Gamma Page"}),
]


@pytest.mark.parametrize("rules,names", FILTER_CASES)
def test_list_and_at_honour_field_filters(client, seeded, rules, names):
    h = _auth(client)
    flt = _grp(*rules)
    listed = client.get("/omnichannel/channels", headers=h, params={"filter": flt})
    assert listed.status_code == 200, listed.text
    assert {c["name"] for c in listed.json()["data"]} == names
    assert listed.json()["total"] == len(names)
    ordered = [c["name"] for c in listed.json()["data"]]
    for i, name in enumerate(ordered):
        at = client.get("/omnichannel/channels/at", headers=h, params={"filter": flt, "index": i})
        assert at.status_code == 200, at.text
        assert at.json()["total"] == len(names)
        assert at.json()["channel"]["name"] == name
    beyond = client.get("/omnichannel/channels/at", headers=h, params={"filter": flt, "index": len(names)})
    assert beyond.json()["channel"] is None and beyond.json()["total"] == len(names)


def test_filter_control_unfiltered_list_has_everything(client, seeded):
    res = client.get("/omnichannel/channels", headers=_auth(client)).json()
    assert res["total"] == 4


@pytest.mark.parametrize("path", ["/omnichannel/channels", "/omnichannel/channels/at"])
@pytest.mark.parametrize("value", [{"a": 1}, [{"a": 1}]], ids=["dict", "list of dicts"])
def test_non_scalar_filter_value_is_422(client, seeded, path, value):
    params = {"filter": _grp(_cond("name", "contains", value))}
    if path.endswith("/at"):
        params["index"] = 0
    h = _auth(client)
    res = client.get(path, headers=h, params=params)
    assert res.status_code == 422, res.text
    ok = dict(params, filter=_grp(_cond("name", "contains", "Alpha")))  # control
    assert client.get(path, headers=h, params=ok).status_code == 200


def _export(client, **extra):
    return client.post(
        "/omnichannel/channels/export", headers=_auth(client), json={"columns": ["name", "status"], **extra}
    )


def test_export_honours_the_filter(client, seeded):
    everything = _export(client)
    assert everything.status_code == 200
    assert len(everything.text.strip().splitlines()) == 1 + 4  # control: header + four rows
    only = _export(client, filter=json.loads(_grp(_cond("status", "eq", "ERROR"))))
    assert only.status_code == 200, only.text
    rows = only.text.strip().splitlines()[1:]
    assert len(rows) == 3
    assert all(r.endswith("ERROR") for r in rows)


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "bogus"},
        json.loads(_grp(_cond("credentialsJson", "contains", "x"))),
        json.loads(_grp(_cond("name", "contains", {"a": 1}))),
    ],
    ids=["bad shape", "unknown field", "dict value"],
)
def test_export_invalid_filter_is_422(client, seeded, bad):
    assert _export(client, filter=bad).status_code == 422
