"""Plan 59 - the erase call's own log row keeps no phone number (AC-59-01..08).

RED tests written BEFORE the implementation. Black box: real requests through
the app with a real workspace API key, so the real GatewayActivityMiddleware
writes the row; the assertions read ``integration_activity`` rows from the DB.

Contract: for ``DELETE /api/v1/omnichannel/contacts/phone:<number>`` (any case,
percent-encoded or not, any answer) the row's operation and request summary
path read ``phone:<erased>``. Every other call (erase by id, other verbs and
routes with a phone identifier) logs exactly as before.

Every test seeds its own chain. Fake numbers only.
"""
import json

import pytest

from app.models.integration_activity import ACTIVITY_SUCCESS, IntegrationActivity
from tests.test_omnichannel_api_gateway import _auth, _mint
from tests.test_omnichannel_contact_erase import Rig, _contact, _env  # noqa: F401 (autouse fixture)
from tests.test_omnichannel_api_gateway import _seed_second_workspace

BASE = "/api/v1/omnichannel/contacts"
ERASED = "phone:<erased>"


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


def _rows(sf):
    db = sf()
    try:
        return db.query(IntegrationActivity).filter(IntegrationActivity.operation.like("%/contacts/%")).all()
    finally:
        db.close()


def _only(sf):
    rows = _rows(sf)
    assert len(rows) == 1, [r.operation for r in rows]
    return rows[0]


def _everything(row):
    """Every column of the row serialized, JSON summaries included."""
    return json.dumps({c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str)


def _assert_masked(row, number):
    digits = "".join(ch for ch in number if ch.isdigit())
    assert row.operation == f"DELETE /contacts/{ERASED}"
    assert row.request_summary_json["path"] == f"/api/v1/omnichannel/contacts/{ERASED}"
    assert digits not in _everything(row)


# AC-59-01
def test_ac_59_01_erase_by_phone_row_keeps_no_number(rig):
    number = "+60100005901"
    _contact(rig.sf, rig.ws, number)
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 200, res.text
    _assert_masked(_only(rig.sf), number)


# AC-59-02
def test_ac_59_02_unknown_number_row_is_masked(rig):
    number = "+60100005902"
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 404
    _assert_masked(_only(rig.sf), number)


def test_ac_59_02_contact_of_another_workspace_row_is_masked(rig):
    number = "+60100005912"
    other_ws = _seed_second_workspace(rig.sf)
    _contact(rig.sf, other_ws, number)
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 404
    _assert_masked(_only(rig.sf), number)


def test_ac_59_02_second_erase_of_the_same_number_row_is_masked(rig):
    number = "+60100005922"
    _contact(rig.sf, rig.ws, number)
    assert rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr).status_code == 200
    assert rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr).status_code == 404
    rows = _rows(rig.sf)
    assert len(rows) == 2
    for row in rows:
        _assert_masked(row, number)


# AC-59-03
@pytest.mark.parametrize(
    "segment",
    ["PHONE:+60100005903", "Phone:+60100005903", "phone%3A%2B60100005903", "PHONE%3A%2b60100005903"],
)
def test_ac_59_03_case_and_encoded_forms_are_masked_the_same_way(rig, segment):
    _contact(rig.sf, rig.ws, "+60100005903")
    res = rig.client.delete(f"{BASE}/{segment}", headers=rig.hdr)
    assert res.status_code == 200, res.text
    _assert_masked(_only(rig.sf), "+60100005903")


@pytest.mark.parametrize(
    "prefix,form,number",
    [
        ("%20", "phone%3A%2B{n}", "+60100005931"),
        ("%C2%A0", "phone:+{n}", "+60100005932"),
        ("%0B", "phone:+{n}", "+60100005933"),
        ("%E2%80%83", "PHONE:+{n}", "+60100005934"),
        ("%E3%80%80", "Phone:+{n}", "+60100005935"),
    ],
)
def test_ac_59_03_padded_phone_identifier_is_masked_too(rig, prefix, form, number):
    _contact(rig.sf, rig.ws, number)
    segment = prefix + form.format(n=number[1:])
    res = rig.client.delete(f"{BASE}/{segment}", headers=rig.hdr)
    assert res.status_code == 200, res.text
    _assert_masked(_only(rig.sf), number)


# AC-59-04 (control)
def test_ac_59_04_bad_and_revoked_key_write_no_row(rig, client):
    number = "+60100005904"
    _contact(rig.sf, rig.ws, number)
    bad = client.delete(f"{BASE}/phone:{number}", headers={"Authorization": "Bearer fxw_live_notakey"})
    assert bad.status_code == 401
    minted = _mint(client, rig.ws, "to-revoke").json()
    rev = client.post(
        f"/omnichannel/workspaces/{rig.ws}/api-keys/{minted['key']['id']}/revoke", headers=_auth(client)
    )
    assert rev.status_code == 200
    revoked = client.delete(
        f"{BASE}/phone:{number}", headers={"Authorization": f"Bearer {minted['fullKey']}"}
    )
    assert revoked.status_code == 401
    assert _rows(rig.sf) == []


# AC-59-05 (control)
def test_ac_59_05_erase_by_id_and_bare_uuid_keep_the_id(rig):
    first = _contact(rig.sf, rig.ws, "+60100005905")
    second = _contact(rig.sf, rig.ws, "+60100005915")
    assert rig.client.delete(f"{BASE}/id:{first}", headers=rig.hdr).status_code == 200
    assert rig.client.delete(f"{BASE}/{second}", headers=rig.hdr).status_code == 200
    by_op = {r.operation: r for r in _rows(rig.sf)}
    assert set(by_op) == {f"DELETE /contacts/id:{first}", f"DELETE /contacts/{second}"}
    assert by_op[f"DELETE /contacts/id:{first}"].request_summary_json["path"] == f"{BASE}/id:{first}"
    assert by_op[f"DELETE /contacts/{second}"].request_summary_json["path"] == f"{BASE}/{second}"


# AC-59-06 (control): masking is narrow, only the erase verb on the bare route
def test_ac_59_06_other_phone_routes_keep_the_number(rig):
    number = "+60100005906"
    _contact(rig.sf, rig.ws, number)
    ident = f"phone:{number}"
    calls = [
        ("GET", f"{BASE}/{ident}", None),
        ("GET", f"{BASE}/{ident}/messages", None),
        ("PATCH", f"{BASE}/{ident}", {"firstName": "Renamed"}),
        ("POST", f"{BASE}/{ident}/read", None),
    ]
    for method, url, body in calls:
        res = rig.client.request(method, url, headers=rig.hdr, json=body)
        assert res.status_code < 500, (method, url, res.text)
    ops = {r.operation: r for r in _rows(rig.sf)}
    for method, url, _ in calls:
        op = f"{method} {url[len('/api/v1/omnichannel'):]}"
        assert op in ops, (op, list(ops))
        assert ops[op].request_summary_json["path"] == url
    assert "<erased>" not in " ".join(ops)


# AC-59-07 (control): the row is filled as for any call, the answer is unchanged
def test_ac_59_07_response_and_other_row_fields_unchanged(rig):
    number = "+60100005907"
    cid = _contact(rig.sf, rig.ws, number)
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 200
    body = res.json()
    assert body["contactId"] == cid and {"erasedAt", "messages", "files"} <= set(body)
    row = _only(rig.sf)
    assert row.status == ACTIVITY_SUCCESS
    assert row.status_code == 200
    assert row.method == "DELETE"
    assert row.trace_id
    assert row.workspace_id == rig.ws
    assert row.api_key_id
    assert row.response_summary_json is not None
    assert row.latency_ms is not None


# AC-59-08: logging never breaks the request (seam: the repository insert, as
# test_activity_log.test_record_swallows_a_raising_writer uses)
def test_ac_59_08_erase_still_answers_200_when_the_log_write_raises(rig, monkeypatch):
    from app.activity_log.repository import IntegrationActivityRepository

    def _boom(*_a, **_k):
        raise RuntimeError("log store down")

    monkeypatch.setattr(IntegrationActivityRepository, "add", _boom)
    number = "+60100005908"
    _contact(rig.sf, rig.ws, number)
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 200, res.text
    assert _rows(rig.sf) == []


def test_ac_59_08_erase_still_answers_200_when_the_masking_raises(rig, monkeypatch):
    from modules.omnichannel.models import Contact

    def _boom(*_a, **_k):
        raise RuntimeError("masking failed")

    monkeypatch.setattr("app.activity_log.middleware._masked_path", _boom)
    number = "+60100005918"
    cid = _contact(rig.sf, rig.ws, number)
    res = rig.client.delete(f"{BASE}/phone:{number}", headers=rig.hdr)
    assert res.status_code == 200, res.text
    assert res.json()["contactId"] == cid
    db = rig.sf()
    try:
        assert db.query(Contact).filter(Contact.id == cid).count() == 0
    finally:
        db.close()
