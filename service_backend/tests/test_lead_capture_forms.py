"""Lead Capture lane L-A (plan 64): form questions (AC-64-24), Meta test lead
(AC-64-30, S-META F7 delete quirk) and the LIVE gate (AC-64-16), plus tenant
scope and no token in logs or answers (AC-64-70/71).

Never calls real Graph: httpx MockTransport via the prototype harness.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.lead_capture.models import (
    SOURCE_LIVE,
    SOURCE_WAITING_FOR_TEST,
    LcSource,
)
from modules.lead_capture.services import connect_service, leadgen_service

from tests.test_lead_capture_prototype import (  # noqa: F401 - pytest fixtures
    FORM_ID,
    FakeGraph,
    LEAD_ID,
    PAGE_ID,
    PAGE_TOKEN,
    SYSTEM_TOKEN,
    TENANT_B,
    _connect,
    _fake_realtime,
    _fixture,
    _key,
    _leads,
    _login,
    _second_tenant,
    _signed_webhook,
    graph,
    lc,
    posts,
)

QUESTIONS = [
    {"id": "q1", "key": "full_name", "label": "Full name", "type": "FULL_NAME"},
    {"id": "q2", "key": "email", "label": "Email", "type": "EMAIL"},
    {
        "id": "q3",
        "key": "interest",
        "label": "What are you interested in?",
        "type": "CUSTOM",
        "options": [{"key": "solar", "value": "Solar panels"}, {"key": "battery", "value": "Battery"}],
    },
]
OLD_TEST_LEAD = "100000000000077"
NEW_TEST_LEAD = "100000000000078"


class FormGraph(FakeGraph):
    """FakeGraph + the form read with questions and the test_leads edge
    (list / create) and the lead DELETE, with S-META F7's quirks."""

    def __init__(self):
        super().__init__(test_ids=())
        self.questions = QUESTIONS
        self.form_status = 200
        self.form_error_code = 2
        self.existing: list[str] = []
        self.delete_quirk = False  # 1892035 answered, lead still deleted
        self.delete_keeps = False  # delete answers error AND the lead stays
        self.create_conflicts = 0  # how many POSTs answer 1892058 first
        self.created: list[str] = []
        self.list_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/{FORM_ID}/test_leads"):
            self.calls.append(request)
            if request.method == "GET":
                if self.list_status != 200:
                    return httpx.Response(self.list_status, json={"error": {"message": "no", "code": 2}})
                return httpx.Response(200, json={"data": [{"id": i} for i in self.existing + self.test_ids]})
            if request.method == "POST":
                if self.create_conflicts > 0 or self.existing:
                    self.create_conflicts = max(0, self.create_conflicts - 1)
                    return httpx.Response(400, json={"error": {
                        "message": "Test lead already exists for this form.", "code": 2, "error_subcode": 1892058}})
                self.existing = [NEW_TEST_LEAD]
                self.created.append(NEW_TEST_LEAD)
                return httpx.Response(200, json={"id": NEW_TEST_LEAD})
        if request.method == "DELETE":
            self.calls.append(request)
            lead_id = path.rsplit("/", 1)[-1]
            if self.delete_keeps:
                return httpx.Response(400, json={"error": {"message": "Could Not Delete Lead", "code": 2,
                                                           "error_subcode": 1892035}})
            self.existing = [i for i in self.existing if i != lead_id]
            if self.delete_quirk:
                return httpx.Response(400, json={"error": {"message": "Could Not Delete Lead", "code": 2,
                                                           "error_subcode": 1892035}})
            return httpx.Response(200, json={"success": True})
        if path.endswith(f"/{FORM_ID}") and request.method == "GET" and "questions" in (request.url.params.get("fields") or ""):
            self.calls.append(request)
            if self.form_status != 200:
                return httpx.Response(self.form_status, json={"error": {
                    "message": f"(#{self.form_error_code}) refused {PAGE_TOKEN}", "code": self.form_error_code}})
            return httpx.Response(200, json={"id": FORM_ID, "name": "Solar form", "questions": self.questions})
        return super().handler(request)


@pytest.fixture
def fgraph(graph, monkeypatch):
    from app.integrations.meta import pages as meta_pages
    from modules.lead_capture import meta_leads

    g = FormGraph()
    monkeypatch.setattr(meta_leads.MetaLeadClient, "_http", lambda self: g.client())
    monkeypatch.setattr(meta_pages.MetaPages, "_http", lambda self: g.client())
    return g


def _source_id(client, headers) -> str:
    res = _connect(client, headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _status(lc, source_id: str) -> str:
    db = lc()
    try:
        return db.get(LcSource, source_id).status
    finally:
        db.close()


# ── questions (AC-64-24) ────────────────────────────────────────────────────

def test_questions_over_gateway_and_staff_include_options(client, lc, fgraph, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    expected = [
        {"key": "full_name", "label": "Full name", "type": "FULL_NAME", "options": []},
        {"key": "email", "label": "Email", "type": "EMAIL", "options": []},
        {"key": "interest", "label": "What are you interested in?", "type": "CUSTOM",
         "options": [{"key": "solar", "value": "Solar panels"}, {"key": "battery", "value": "Battery"}]},
    ]
    gw = client.get(f"/api/v1/lead-capture/sources/{sid}/forms/{FORM_ID}/questions", headers=_bearer(key))
    assert gw.status_code == 200, gw.text
    assert gw.json() == {"formId": FORM_ID, "formName": "Solar form", "data": expected}
    staff = client.get(f"/lead-capture/sources/{sid}/forms/{FORM_ID}/questions", headers=headers)
    assert staff.status_code == 200, staff.text
    assert staff.json()["data"] == expected
    # read with the Page token, in the header
    read = next(c for c in fgraph.calls if "questions" in (c.url.params.get("fields") or ""))
    assert read.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
    assert read.url.params.get("fields") == "name,questions"
    for text in (gw.text, staff.text, caplog.text):
        assert PAGE_TOKEN not in text and SYSTEM_TOKEN not in text


def test_questions_tenant_b_cannot_read_a_source(client, lc, fgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _second_tenant(lc, False)
    db = lc()
    try:
        from modules.lead_capture.services import key_service

        _row, key_b = key_service.issue(db, TENANT_B, name="B", created_by=None)
    finally:
        db.close()
    res = client.get(f"/api/v1/lead-capture/sources/{sid}/forms/{FORM_ID}/questions", headers=_bearer(key_b))
    assert res.status_code == 404 and res.json()["error"]["code"] == "source_not_found"
    res = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=_bearer(key_b))
    assert res.status_code == 404 and res.json()["error"]["code"] == "source_not_found"
    assert not any(c.method == "POST" and c.url.path.endswith("/test_leads") for c in fgraph.calls)


@pytest.mark.parametrize("code,expected", [(190, "token_invalid"), (100, "meta_refused")])
def test_questions_meta_error_is_typed_never_500(client, lc, fgraph, caplog, code, expected):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    fgraph.form_status = 400
    fgraph.form_error_code = code
    res = client.get(f"/api/v1/lead-capture/sources/{sid}/forms/{FORM_ID}/questions", headers=_bearer(key))
    assert res.status_code == 400, res.text
    assert res.json()["error"]["code"] == expected
    assert PAGE_TOKEN not in res.text and PAGE_TOKEN not in caplog.text


def test_bad_form_id_is_422(client, lc, fgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    res = client.get(f"/api/v1/lead-capture/sources/{sid}/forms/abc..x/questions", headers=_bearer(key))
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_form_id"
    res = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": "../x"}, headers=_bearer(key))
    assert res.status_code == 422


# ── test lead (AC-64-30, S-META F7) ─────────────────────────────────────────

def _test_lead_calls(fgraph):
    return [(c.method, c.url.path.rsplit("/", 1)[-1]) for c in fgraph.calls
            if c.url.path.endswith("/test_leads") or c.method == "DELETE"]


def test_test_lead_creates_when_none_exists(client, lc, fgraph, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    res = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=_bearer(key))
    assert res.status_code == 202, res.text
    assert res.json() == {"formId": FORM_ID}
    assert fgraph.created == [NEW_TEST_LEAD]
    post = next(c for c in fgraph.calls if c.method == "POST" and c.url.path.endswith("/test_leads"))
    assert post.headers["Authorization"] == f"Bearer {PAGE_TOKEN}" and PAGE_TOKEN not in str(post.url)
    assert PAGE_TOKEN not in res.text and PAGE_TOKEN not in caplog.text


def test_test_lead_delete_quirk_rereads_then_creates(client, lc, fgraph):
    """DELETE answers 1892035 but the lead is gone: re-read, then create."""
    fgraph.existing = [OLD_TEST_LEAD]
    fgraph.delete_quirk = True
    headers = _login(client)
    sid = _source_id(client, headers)
    res = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert res.status_code == 202, res.text
    assert _test_lead_calls(fgraph) == [
        ("GET", "test_leads"), ("DELETE", OLD_TEST_LEAD), ("GET", "test_leads"), ("POST", "test_leads"),
    ]
    assert fgraph.created == [NEW_TEST_LEAD]


def test_test_lead_that_really_stays_is_refused_without_post(client, lc, fgraph):
    fgraph.existing = [OLD_TEST_LEAD]
    fgraph.delete_keeps = True
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    res = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=_bearer(key))
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "test_lead_exists"
    assert fgraph.created == []
    assert not any(c.method == "POST" and c.url.path.endswith("/test_leads") for c in fgraph.calls)


def test_already_exists_1892058_clears_and_retries_once(client, lc, fgraph):
    """A test lead created between our read and our POST (1892058): clear it
    and send once more."""
    fgraph.create_conflicts = 1
    headers = _login(client)
    sid = _source_id(client, headers)
    res = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert res.status_code == 202, res.text
    assert fgraph.created == [NEW_TEST_LEAD]
    assert [m for m, _ in _test_lead_calls(fgraph)].count("POST") == 2


def test_already_exists_twice_is_409(client, lc, fgraph):
    fgraph.create_conflicts = 5
    headers = _login(client)
    sid = _source_id(client, headers)
    res = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "test_lead_exists"
    assert [m for m, _ in _test_lead_calls(fgraph)].count("POST") == 2


def test_test_lead_list_error_is_typed(client, lc, fgraph):
    fgraph.list_status = 400
    headers = _login(client)
    sid = _source_id(client, headers)
    res = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "meta_refused"


# ── LIVE gate (AC-64-16) ────────────────────────────────────────────────────

def test_new_connect_waits_for_test_and_test_lead_flips_live(client, lc, fgraph, posts):
    headers = _login(client)
    res = _connect(client, headers)
    assert res.status_code == 201 and res.json()["status"] == SOURCE_WAITING_FOR_TEST
    sid = res.json()["id"]
    # reconnect while waiting: same row, still waiting
    again = _connect(client, headers)
    assert again.json()["id"] == sid and again.json()["status"] == SOURCE_WAITING_FOR_TEST
    # the webhook still routes to a waiting source; the test lead flips it
    fgraph.test_ids = [LEAD_ID]
    assert _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json")).status_code == 200
    (lead,) = _leads(lc)
    assert lead.is_test is True
    assert _status(lc, sid) == SOURCE_LIVE
    src = client.get("/lead-capture/sources", headers=headers).json()["data"][0]
    assert src["status"] == SOURCE_LIVE


def test_real_lead_delivers_but_does_not_flip(client, lc, fgraph, posts):
    fgraph.lead = {**fgraph.lead, "ad_id": "500000000000001"}
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    client.post("/api/v1/lead-capture/webhooks", json={"url": "https://consumer.example/leads",
                                                       "events": ["lead.created"]}, headers=_bearer(key))
    _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json"))
    (lead,) = _leads(lc)
    assert lead.is_test is False
    assert len(posts) == 1  # delivered while waiting
    assert _status(lc, sid) == SOURCE_WAITING_FOR_TEST


def test_existing_live_source_stays_live_on_reconnect_and_leads(client, lc, fgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    db = lc()
    try:
        db.get(LcSource, sid).status = SOURCE_LIVE  # the prod source, connected before the gate
        db.commit()
    finally:
        db.close()
    assert _connect(client, headers).json()["status"] == SOURCE_LIVE
    fgraph.lead = {**fgraph.lead, "ad_id": "500000000000001"}
    db = lc()
    try:
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _status(lc, sid) == SOURCE_LIVE
    db = lc()
    try:
        assert db.query(LcSource).count() == 1
    finally:
        db.close()


def test_waiting_source_blocks_another_tenant_like_live(client, lc, fgraph):
    """D13 sharing guard applies to a Page still waiting for its test."""
    _second_tenant(lc, False)
    db = lc()
    try:
        row = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        assert row.status == SOURCE_WAITING_FOR_TEST
    finally:
        db.close()
    res = _connect(client, _login(client))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PAGE_IN_USE"


def test_test_lead_flips_only_its_own_source_on_a_shared_page(lc, fgraph):
    _second_tenant(lc, True)
    fgraph.test_ids = [LEAD_ID]
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        a = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        a.status = SOURCE_LIVE
        db.commit()
        a_id, b_id = a.id, b.id
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _status(lc, a_id) == SOURCE_LIVE and _status(lc, b_id) == SOURCE_LIVE
    assert len(_leads(lc)) == 2
