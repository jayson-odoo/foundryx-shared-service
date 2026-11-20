"""Plan 38 gap 7, slice S4: business hours under the API key (AC-38-143,
AC-38-144). RED tests written before the implementation.

Contract: plan 38 "Wire contract" S4. `GET/PUT /api/v1/omnichannel/business-hours`
for the key's own workspace. Response `{workspaceId, timezone, windows, source}`;
`source` is `workspace`, `tenant` or `none`. Bad body: 422 `invalid_request` with
`details.fieldErrors` keyed `timezone` / `windows`.

The parallel-first-write half of AC-38-144 is a Postgres probe (S6); here only a
sequential stand-in is driven.
"""
import json

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _default_workspace_id
from tests.test_omnichannel_business_hours import _default_windows
from tests.test_omnichannel_conversations import _auth
from tests.test_omnichannel_key_workflows import BASE, _key, _new_workspace

URL = f"{BASE}/business-hours"
EMPTY = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def _settings_cls():
    from modules.omnichannel.models import OmnichannelSettings

    return OmnichannelSettings


def _put_row(session_factory, ws, tz, windows):
    """Direct seed: ws=None is the tenant default."""
    db = session_factory()
    try:
        db.add(_settings_cls()(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws,
                               business_timezone=tz, business_hours_json=windows))
        db.commit()
    finally:
        db.close()


def _rows(session_factory):
    db = session_factory()
    try:
        return sorted(
            (r.workspace_id or "", r.business_timezone, json.dumps(r.business_hours_json, sort_keys=True))
            for r in db.query(_settings_cls()).filter(_settings_cls().tenant_id == DEFAULT_TENANT_ID).all()
        )
    finally:
        db.close()


def _rig(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory)
    _, hdr = _key(client, ws)
    return ws, ws2, hdr


# -- AC-38-143 ------------------------------------------------------------------
def test_ac_38_143_get_source_workspace_tenant_none(client, session_factory):
    ws, ws2, hdr = _rig(client, session_factory)

    # neither set -> none, dashboard-shaped body
    r = client.get(URL, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json() == {"workspaceId": ws, "timezone": None, "windows": EMPTY, "source": "none"}

    # another workspace's row is never returned
    other = dict(_default_windows(), sat=[{"from": "10:00", "to": "12:00"}])
    _put_row(session_factory, ws2, "Asia/Tokyo", other)
    r = client.get(URL, headers=hdr)
    assert r.json()["source"] == "none" and r.json()["timezone"] is None
    assert "Asia/Tokyo" not in r.text

    # only a tenant default -> source tenant with the default's timezone and windows
    tenant_windows = dict(_default_windows(), sun=[{"from": "08:00", "to": "09:00"}])
    _put_row(session_factory, None, "Europe/Paris", tenant_windows)
    r = client.get(URL, headers=hdr)
    body = r.json()
    assert body["source"] == "tenant" and body["workspaceId"] == ws
    assert body["timezone"] == "Europe/Paris" and body["windows"] == tenant_windows
    assert "Asia/Tokyo" not in r.text

    # the workspace's own row wins
    own = dict(_default_windows(), sat=[{"from": "09:00", "to": "13:00"}])
    _put_row(session_factory, ws, "Asia/Kuala_Lumpur", own)
    body = client.get(URL, headers=hdr).json()
    assert body["source"] == "workspace"
    assert body["timezone"] == "Asia/Kuala_Lumpur" and body["windows"] == own


# -- AC-38-144 ------------------------------------------------------------------
def test_ac_38_144_put_own_row_only_and_validation(client, session_factory):
    ws, ws2, hdr = _rig(client, session_factory)
    tenant_windows = _default_windows()
    other_windows = dict(_default_windows(), sat=[{"from": "10:00", "to": "12:00"}])
    _put_row(session_factory, None, "Europe/Paris", tenant_windows)
    _put_row(session_factory, ws2, "Asia/Tokyo", other_windows)
    untouched = _rows(session_factory)

    # first write creates the key workspace's row, and only that
    new_windows = dict(_default_windows(), sat=[{"from": "09:00", "to": "13:00"}])
    r = client.put(URL, json={"timezone": "Asia/Kuala_Lumpur", "windows": new_windows}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json() == {"workspaceId": ws, "timezone": "Asia/Kuala_Lumpur",
                        "windows": new_windows, "source": "workspace"}
    after = _rows(session_factory)
    assert len(after) == len(untouched) + 1
    assert [x for x in after if x[0] != ws] == untouched, "tenant default and other workspace untouched"

    # a second write updates that row in place
    r = client.put(URL, json={"timezone": "UTC", "windows": _default_windows()}, headers=hdr)
    assert r.status_code == 200 and r.json()["timezone"] == "UTC"
    assert len(_rows(session_factory)) == len(untouched) + 1
    assert [x for x in _rows(session_factory) if x[0] != ws] == untouched

    # validation: nothing written, field errors keyed like the dashboard's
    snapshot = _rows(session_factory)
    bad_tz = client.put(URL, json={"timezone": "Mars/Olympus", "windows": _default_windows()}, headers=hdr)
    assert bad_tz.status_code == 422, bad_tz.text
    assert bad_tz.json()["error"]["code"] == "invalid_request"
    assert "timezone" in bad_tz.json()["error"]["details"]["fieldErrors"]
    bad_win = client.put(URL, json={"timezone": "UTC", "windows": {"mon": [{"from": "25:99", "to": "x"}]}},
                         headers=hdr)
    assert bad_win.status_code == 422, bad_win.text
    assert bad_win.json()["error"]["code"] == "invalid_request"
    assert "windows" in bad_win.json()["error"]["details"]["fieldErrors"]
    for body in ({"windows": _default_windows()}, {"timezone": "UTC"}, {"timezone": 5, "windows": []}):
        r = client.put(URL, json=body, headers=hdr)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request", (body, r.text)

    # body caps: not JSON, or far over 256 KB
    r = client.put(URL, content=b"not json", headers={**hdr, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    big = json.dumps({"timezone": "UTC", "windows": {"mon": [], "pad": "a" * (300 * 1024)}})
    r = client.put(URL, content=big.encode(), headers={**hdr, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert _rows(session_factory) == snapshot, "no refused write changed anything"


def test_ac_38_144_dashboard_and_node_read_new_value(client, session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_business_hours

    ws, ws2, hdr = _rig(client, session_factory)
    staff = _auth(client)
    windows = dict(_default_windows(), sat=[{"from": "09:00", "to": "13:00"}])
    r = client.put(URL, json={"timezone": "Asia/Kuala_Lumpur", "windows": windows}, headers=hdr)
    assert r.status_code == 200, r.text

    dash = client.get(f"/omnichannel/workspaces/{ws}/business-hours", headers=staff)
    assert dash.status_code == 200
    assert dash.json()["timezone"] == "Asia/Kuala_Lumpur" and dash.json()["windows"] == windows

    db = session_factory()
    try:
        out = omnichannel_business_hours(db, DEFAULT_TENANT_ID, {"workspaceId": ws}, {})
        assert out["timezone"] == "Asia/Kuala_Lumpur"
    finally:
        db.close()

    # a second write to closed-all-week flips the node to outside, and the dashboard follows
    r = client.put(URL, json={"timezone": "UTC", "windows": EMPTY}, headers=hdr)
    assert r.status_code == 200, r.text
    db = session_factory()
    try:
        out = omnichannel_business_hours(db, DEFAULT_TENANT_ID, {"workspaceId": ws}, {})
        assert out["timezone"] == "UTC" and out["branch"] == "outside" and out["isOpen"] is False
    finally:
        db.close()
    assert client.get(f"/omnichannel/workspaces/{ws}/business-hours", headers=staff).json()["windows"] == EMPTY


def test_ac_38_144_first_write_race_stand_in_sequential(client, session_factory, monkeypatch):
    """Sequential stand-in for two parallel first writes: the workspace row appears after
    the writer looked and found none (its first lookup is forced to answer None). The write
    must still answer 200, leave ONE row for the workspace and hold the new value."""
    from modules.omnichannel.services.business_hours import BusinessHoursService

    ws, ws2, hdr = _rig(client, session_factory)
    _put_row(session_factory, ws, "Europe/Paris", _default_windows())  # the other writer's row

    real = BusinessHoursService._row
    state = {"hidden": False}

    def row(self, tenant_id, workspace_id):
        if workspace_id == ws and not state["hidden"]:
            state["hidden"] = True
            return None
        return real(self, tenant_id, workspace_id)

    monkeypatch.setattr(BusinessHoursService, "_row", row)
    mine = dict(_default_windows(), sun=[{"from": "08:00", "to": "09:00"}])
    r = client.put(URL, json={"timezone": "Asia/Kuala_Lumpur", "windows": mine}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Asia/Kuala_Lumpur" and r.json()["source"] == "workspace"
    monkeypatch.undo()
    mine_rows = [x for x in _rows(session_factory) if x[0] == ws]
    assert len(mine_rows) == 1 and mine_rows[0][1] == "Asia/Kuala_Lumpur"
