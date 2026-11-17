"""Lead Capture lane L-B (plan 64): forms filter (AC-64-23), backfill
(AC-64-28), token health (AC-64-29), reconnect, disconnect (AC-64-09/37),
source history, plus the three L-A gaps the owner folded in (17 Nov):
test-lead cooldown, a shared-Page test lead flips only the source that asked
for it, and reconnecting a disconnected source reuses its row.

Never calls real Graph: httpx MockTransport on top of the prototype harness.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.email_outbox import EmailOutbox
from modules.lead_capture.models import (
    SOURCE_DISCONNECTED,
    SOURCE_LIVE,
    SOURCE_NEEDS_RECONNECT,
    SOURCE_WAITING_FOR_TEST,
    LcLead,
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

FORM_ID2 = "400000000000002"
FORM_ID3 = "400000000000003"
MISSED_LEAD = "100000000000101"
NEW_FORM_LEAD = "100000000000102"
FORM2_LEAD = "100000000000103"


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _meta_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _lead_body(lead_id: str, form_id: str, created: datetime, email: str = "x@example.com") -> dict:
    return {
        "id": lead_id,
        "created_time": _meta_time(created),
        "form_id": form_id,
        "ad_id": "500000000000001",
        "field_data": [
            {"name": "full_name", "values": ["Back Fill"]},
            {"name": "email", "values": [email]},
        ],
    }


class LbGraph(FakeGraph):
    """FakeGraph + the Page's form list, a form's lead list, the Page's
    leadgen Terms flag, a stateful subscribed_apps edge and a dead-token mode."""

    def __init__(self):
        super().__init__()
        self.page_fields = ["messages"]
        now = datetime.now(timezone.utc)
        self.forms = [
            {"id": FORM_ID, "name": "Solar form", "status": "ACTIVE", "created_time": _meta_time(now - timedelta(days=30))},
            {"id": FORM_ID2, "name": "Battery form", "status": "ARCHIVED", "created_time": _meta_time(now - timedelta(days=20))},
        ]
        self.form_leads: dict = {}
        self.tos = False
        self.dead = False
        self.dead_code = 190
        self.leads_filters: list = []
        self.form_errors: dict = {}

    def _dead(self) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": f"Error validating access token {PAGE_TOKEN}", "code": self.dead_code}}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("Authorization", "")
        if self.dead and auth == f"Bearer {PAGE_TOKEN}":
            self.calls.append(request)
            return self._dead()
        if path.endswith(f"/{PAGE_ID}/subscribed_apps"):
            self.calls.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"data": [{"id": "app-123", "subscribed_fields": list(self.page_fields)}]})
            if request.method == "DELETE":
                self.page_fields = []
                return httpx.Response(200, json={"success": True})
            self.page_fields = request.url.params.get("subscribed_fields", "").split(",")
            self.subscribed = list(self.page_fields)
            return httpx.Response(200, json={"success": True})
        if path.endswith(f"/{PAGE_ID}/leadgen_forms"):
            self.calls.append(request)
            return httpx.Response(200, json={"data": list(self.forms)})
        if path.endswith(f"/{PAGE_ID}") and "leadgen_tos_accepted" in (request.url.params.get("fields") or ""):
            self.calls.append(request)
            return httpx.Response(200, json={"id": PAGE_ID, "leadgen_tos_accepted": self.tos})
        if path.endswith("/leads") and request.method == "GET":
            self.calls.append(request)
            form_id = path.rsplit("/", 2)[-2]
            if form_id in self.form_errors:
                code = self.form_errors[form_id]
                return httpx.Response(400, json={"error": {"message": f"(#{code}) refused", "code": code}})
            filtering = json.loads(request.url.params.get("filtering") or "[]")
            self.leads_filters.append((form_id, filtering))
            since = next((int(f["value"]) for f in filtering
                          if f.get("field") == "time_created" and f.get("operator") == "GREATER_THAN"), 0)
            until = next((int(f["value"]) for f in filtering
                          if f.get("field") == "time_created" and f.get("operator") == "LESS_THAN"), 10**12)
            rows = [
                r for r in self.form_leads.get(form_id, [])
                if since < _epoch(datetime.strptime(r["created_time"], "%Y-%m-%dT%H:%M:%S%z")) < until
            ]
            rows.sort(key=lambda r: r["created_time"], reverse=True)  # Meta: newest first
            limit = int(request.url.params.get("limit") or 100)
            offset = int(request.url.params.get("after") or 0)
            page = rows[offset:offset + limit]
            paging = {}
            if offset + limit < len(rows):
                paging = {"cursors": {"after": str(offset + limit)}, "next": "https://graph.example/next"}
            return httpx.Response(200, json={"data": page, "paging": paging})
        return super().handler(request)


@pytest.fixture
def lgraph(graph, monkeypatch):
    from app.integrations.meta import pages as meta_pages
    from modules.lead_capture import meta_leads

    g = LbGraph()
    monkeypatch.setattr(meta_leads.MetaLeadClient, "_http", lambda self: g.client())
    monkeypatch.setattr(meta_pages.MetaPages, "_http", lambda self: g.client())
    return g


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _source_id(client, headers) -> str:
    res = _connect(client, headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _row(lc, source_id: str) -> LcSource:
    db = lc()
    try:
        row = db.get(LcSource, source_id)
        db.expunge(row)
        return row
    finally:
        db.close()


def _set(lc, source_id: str, **values) -> None:
    db = lc()
    try:
        row = db.get(LcSource, source_id)
        for k, v in values.items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


def _endpoint(client, key, events=("lead.created", "source.updated")):
    res = client.post(
        "/api/v1/lead-capture/webhooks",
        json={"url": "https://consumer.example/leads", "events": list(events)},
        headers=_bearer(key),
    )
    assert res.status_code == 201, res.text


def _events(posts, name):
    return [json.loads(p["body"]) for p in posts if p["headers"].get("X-Lead-Capture-Event") == name]


def _mails(lc):
    db = lc()
    try:
        return [m for m in db.query(EmailOutbox).all() if (m.template_key or "").startswith("lead_capture.")]
    finally:
        db.close()


# ── forms (AC-64-23) ────────────────────────────────────────────────────────

def test_forms_list_over_gateway_and_staff(client, lc, lgraph, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    for res in (
        client.get(f"/lead-capture/sources/{sid}/forms", headers=headers),
        client.get(f"/api/v1/lead-capture/sources/{sid}/forms", headers=_bearer(key)),
    ):
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["formsMode"] == "all" and body["formIds"] == []
        assert body["tosAccepted"] is False
        assert [(f["id"], f["name"], f["status"]) for f in body["data"]] == [
            (FORM_ID, "Solar form", "ACTIVE"), (FORM_ID2, "Battery form", "ARCHIVED")]
        assert body["data"][0]["createdAt"].endswith("Z")
        assert PAGE_TOKEN not in res.text
    call = next(c for c in lgraph.calls if c.url.path.endswith("/leadgen_forms"))
    assert call.headers["Authorization"] == f"Bearer {PAGE_TOKEN}" and PAGE_TOKEN not in str(call.url)
    assert PAGE_TOKEN not in caplog.text and SYSTEM_TOKEN not in caplog.text


def test_put_forms_pick_needs_ids_and_is_stored(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    bad = client.put(f"/api/v1/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": []},
                     headers=_bearer(key))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "forms_required"
    bad = client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "some", "formIds": [FORM_ID]},
                     headers=headers)
    assert bad.status_code == 422
    bad = client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": ["abc"]},
                     headers=headers)
    assert bad.status_code == 422
    ok = client.put(f"/api/v1/lead-capture/sources/{sid}/forms",
                    json={"formsMode": "pick", "formIds": [FORM_ID2, FORM_ID2]}, headers=_bearer(key))
    assert ok.status_code == 200, ok.text
    assert ok.json()["formsMode"] == "pick" and ok.json()["formIds"] == [FORM_ID2]
    assert _row(lc, sid).config_json["formIds"] == [FORM_ID2]
    back = client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "all"}, headers=headers)
    assert back.status_code == 200 and back.json()["formsMode"] == "all" and back.json()["formIds"] == []


def test_pick_mode_filters_ingest_all_mode_does_not(client, lc, lgraph, posts):
    headers = _login(client)
    sid = _source_id(client, headers)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID2]}, headers=headers)
    lgraph.calls.clear()
    db = lc()
    try:
        assert leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID) == []
    finally:
        db.close()
    assert _leads(lc) == []
    assert not any(c.url.path.endswith(f"/{LEAD_ID}") for c in lgraph.calls)  # filtered before the read
    lgraph.extra_leads[FORM2_LEAD] = _lead_body(FORM2_LEAD, FORM_ID2, datetime.now(timezone.utc))
    db = lc()
    try:
        assert len(leadgen_service.process_leadgen(db, PAGE_ID, FORM2_LEAD, FORM_ID2)) == 1
    finally:
        db.close()
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "all"}, headers=headers)
    db = lc()
    try:
        assert len(leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)) == 1
    finally:
        db.close()
    assert {lead.form_id for lead in _leads(lc)} == {FORM_ID, FORM_ID2}


def test_pick_mode_filters_on_the_lead_form_when_the_webhook_has_none(lc, lgraph):
    db = lc()
    try:
        src = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        src.config_json = {**src.config_json, "formsMode": "pick", "formIds": [FORM_ID2]}
        db.commit()
        assert leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, "") == []  # lead's own form_id is FORM_ID
    finally:
        db.close()
    assert _leads(lc) == []


# ── backfill (AC-64-28) ─────────────────────────────────────────────────────

def _age_source(lc, sid, days=2):
    past = datetime.now(timezone.utc) - timedelta(days=days)
    _set(lc, sid, created_at=past, cursor_at=None)


def test_backfill_finds_a_missed_lead_once_and_a_new_form(client, lc, lgraph, posts):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid)
    key = _key(client, headers)
    _endpoint(client, key, events=("lead.created",))
    now = datetime.now(timezone.utc)
    lgraph.form_leads[FORM_ID] = [_lead_body(MISSED_LEAD, FORM_ID, now - timedelta(hours=3))]
    res = client.post(f"/api/v1/lead-capture/sources/{sid}/backfill", headers=_bearer(key))
    assert res.status_code == 202, res.text
    leads = _leads(lc)
    assert [lead.platform_lead_id for lead in leads] == [MISSED_LEAD]
    assert len(_events(posts, "lead.created")) == 1
    row = _row(lc, sid)
    assert row.cursor_at is not None and row.backfill_last_run_at is not None and row.backfill_last_error is None
    # re-run creates nothing; the cursor rides the next query
    _set(lc, sid, backfill_last_run_at=None)  # past the Run-now cooldown
    res = client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert res.status_code == 202
    assert len(_leads(lc)) == 1 and len(_events(posts, "lead.created")) == 1
    since = lgraph.leads_filters[-1][1][0]["value"]
    assert since >= _epoch(row.cursor_at) - 600
    # a form created after setup (All forms mode) is included from its first lead
    lgraph.forms.append({"id": FORM_ID3, "name": "New form", "status": "ACTIVE",
                         "created_time": _meta_time(now - timedelta(minutes=30))})
    lgraph.form_leads[FORM_ID3] = [_lead_body(NEW_FORM_LEAD, FORM_ID3, now - timedelta(minutes=20))]
    _set(lc, sid, backfill_last_run_at=None)
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert sorted(lead.platform_lead_id for lead in _leads(lc)) == [MISSED_LEAD, NEW_FORM_LEAD]
    new_form_query = next(f for form, f in lgraph.leads_filters if form == FORM_ID3)
    assert new_form_query[0]["value"] >= _epoch(now - timedelta(minutes=31))  # starts at its own creation


def test_backfill_and_webhook_share_the_store_path(client, lc, lgraph, posts):
    """A lead the webhook already stored is not stored again by backfill."""
    headers = _login(client)
    sid = _source_id(client, headers)
    _age_source(lc, sid)
    assert _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json")).status_code == 200
    assert len(_leads(lc)) == 1
    now = datetime.now(timezone.utc)
    lgraph.form_leads[FORM_ID] = [{**lgraph.lead, "created_time": _meta_time(now - timedelta(hours=1))}]
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert len(_leads(lc)) == 1


def test_backfill_caps_at_90_days_and_respects_pick_mode(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, created_at=datetime.now(timezone.utc) - timedelta(days=400), cursor_at=None)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID]}, headers=headers)
    lgraph.forms[0]["created_time"] = _meta_time(datetime.now(timezone.utc) - timedelta(days=300))
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    queried = {form for form, _ in lgraph.leads_filters}
    assert queried == {FORM_ID}  # pick mode: only the ticked form
    since = lgraph.leads_filters[0][1][0]["value"]
    assert since >= _epoch(datetime.now(timezone.utc) - timedelta(days=90, minutes=5))


def test_backfill_beat_covers_routing_sources_only(lc, lgraph):
    from modules.lead_capture.services import backfill_service

    _second_tenant(lc, True)
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        a = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b.status = SOURCE_DISCONNECTED
        a.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
        lgraph.form_leads[FORM_ID] = [_lead_body(MISSED_LEAD, FORM_ID, datetime.now(timezone.utc) - timedelta(hours=2))]
        assert backfill_service.run_due(db) == 1
    finally:
        db.close()
    (lead,) = _leads(lc)
    assert lead.tenant_id == DEFAULT_TENANT_ID


def test_backfill_cross_tenant_is_404(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _second_tenant(lc, False)
    db = lc()
    try:
        from modules.lead_capture.services import key_service

        _row_b, key_b = key_service.issue(db, TENANT_B, name="B", created_by=None)
    finally:
        db.close()
    lgraph.calls.clear()
    for method, path, body in (
        ("post", f"/api/v1/lead-capture/sources/{sid}/backfill", None),
        ("get", f"/api/v1/lead-capture/sources/{sid}/forms", None),
        ("put", f"/api/v1/lead-capture/sources/{sid}/forms", {"formsMode": "all"}),
        ("delete", f"/api/v1/lead-capture/sources/{sid}", None),
        ("get", f"/api/v1/lead-capture/sources/{sid}/history", None),
    ):
        kwargs = {"headers": _bearer(key_b)}
        if body is not None:
            kwargs["json"] = body
        res = getattr(client, method)(path, **kwargs)
        assert res.status_code == 404, (path, res.text)
        assert res.json()["error"]["code"] == "source_not_found"
    assert lgraph.calls == []
    assert _row(lc, sid).status == SOURCE_WAITING_FOR_TEST


# ── token health (AC-64-29) ─────────────────────────────────────────────────

def test_token_error_flips_needs_reconnect_with_one_event_and_one_mail(client, lc, lgraph, posts, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    key = _key(client, headers)
    _endpoint(client, key)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT
    updated = _events(posts, "source.updated")
    assert len(updated) == 1
    data = updated[0]["data"]
    assert data["id"] == sid and data["status"] == SOURCE_NEEDS_RECONNECT and data["change"] == "needs_reconnect"
    (mail,) = _mails(lc)
    text = mail.subject + mail.text_body + mail.html_body
    assert "Foundryx Test Page" in mail.subject  # the Page by name
    assert "Foundryx" not in text.replace("Foundryx Test Page", "")  # white-label
    assert PAGE_TOKEN not in text
    # a second failure (backfill tick, another webhook) sends nothing more
    db = lc()
    try:
        leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
        from modules.lead_capture.services import backfill_service

        backfill_service.run_due(db)
    finally:
        db.close()
    assert len(_events(posts, "source.updated")) == 1 and len(_mails(lc)) == 1
    listed = client.get("/api/v1/lead-capture/sources", headers=_bearer(key)).json()["data"][0]
    assert listed["status"] == SOURCE_NEEDS_RECONNECT
    assert PAGE_TOKEN not in caplog.text and SYSTEM_TOKEN not in caplog.text


def test_permission_removed_code_200_also_flips(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid)
    lgraph.dead, lgraph.dead_code = True, 200
    res = client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert res.status_code == 202
    row = _row(lc, sid)
    assert row.status == SOURCE_NEEDS_RECONNECT and row.backfill_last_error


def test_a_non_token_error_does_not_flip(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    orig = lgraph.handler

    def handler(request):
        if request.url.path.endswith(f"/{LEAD_ID}"):
            return httpx.Response(500, json={"error": {"message": "Service temporarily unavailable", "code": 2}})
        return orig(request)

    lgraph.handler = handler
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _row(lc, sid).status == SOURCE_WAITING_FOR_TEST


def test_shared_page_one_dead_token_keeps_the_other_tenant(lc, lgraph):
    """AC-64-37: tenant A's token dies; B still gets the lead, A goes
    NEEDS_RECONNECT, the Page subscription is untouched."""
    _second_tenant(lc, True)
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        a = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        from app.secrets import encrypt_secret

        a.credentials_encrypted = encrypt_secret({"pageToken": "DEADtokenA", "dev": False})
        a.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        a_id, b_id = a.id, b.id
    finally:
        db.close()
    orig = lgraph.handler

    def handler(request):
        if request.headers.get("Authorization") == "Bearer DEADtokenA":
            lgraph.calls.append(request)
            return httpx.Response(400, json={"error": {"message": "Error validating access token", "code": 190}})
        return orig(request)

    lgraph.handler = handler
    db = lc()
    try:
        created = leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert len(created) == 1
    assert {lead.source_id for lead in _leads(lc)} == {b_id}
    assert _row(lc, a_id).status == SOURCE_NEEDS_RECONNECT
    assert _row(lc, b_id).status != SOURCE_NEEDS_RECONNECT
    assert "leadgen" in lgraph.page_fields


# ── reconnect ───────────────────────────────────────────────────────────────

def test_reconnect_after_needs_reconnect_keeps_id_map_leads_and_recovers(client, lc, lgraph, posts):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid)
    client.put("/lead-capture/sources/{}/field-map".format(sid),
               json={"formId": FORM_ID, "map": {"email": "email"}}, headers=headers)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID]}, headers=headers)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT
    # the lead sent meanwhile is in the form's list; reconnect recovers it
    lgraph.dead = False
    lgraph.form_leads[FORM_ID] = [_lead_body(MISSED_LEAD, FORM_ID, datetime.now(timezone.utc) - timedelta(minutes=10))]
    res = _connect(client, headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"] == sid and body["status"] == SOURCE_LIVE
    assert body["fieldMap"] == {FORM_ID: {"email": "email"}}
    assert body["formsMode"] == "pick" and body["formIds"] == [FORM_ID]
    assert [lead.platform_lead_id for lead in _leads(lc)] == [MISSED_LEAD]
    db = lc()
    try:
        assert db.query(LcSource).count() == 1
    finally:
        db.close()


def test_reconnect_a_disconnected_source_reuses_its_row(client, lc, lgraph):
    """L-A gap (c): a disconnected source comes back as the same row."""
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    assert client.delete(f"/lead-capture/sources/{sid}", headers=headers).status_code == 204
    assert _row(lc, sid).status == SOURCE_DISCONNECTED
    res = _connect(client, headers)
    assert res.status_code == 201
    assert res.json()["id"] == sid and res.json()["status"] == SOURCE_LIVE
    db = lc()
    try:
        assert db.query(LcSource).count() == 1
    finally:
        db.close()


def test_reconnect_of_a_disconnected_source_that_never_passed_its_test_waits(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    client.delete(f"/lead-capture/sources/{sid}", headers=headers)
    res = _connect(client, headers)
    assert res.json()["id"] == sid and res.json()["status"] == SOURCE_WAITING_FOR_TEST


def test_reconnect_of_a_disconnected_row_still_follows_the_sharing_rule(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    client.delete(f"/lead-capture/sources/{sid}", headers=headers)
    _second_tenant(lc, False)
    db = lc()
    try:
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
    finally:
        db.close()
    res = _connect(client, headers)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PAGE_IN_USE"
    assert _row(lc, sid).status == SOURCE_DISCONNECTED


# ── disconnect (AC-64-09/37) ────────────────────────────────────────────────

def test_disconnect_keeps_leads_wipes_token_and_unsubscribes_last_holder(client, lc, lgraph, posts):
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    _endpoint(client, key)
    assert lgraph.page_fields == ["messages", "leadgen"]
    _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json"))
    assert len(_leads(lc)) == 1
    res = client.delete(f"/api/v1/lead-capture/sources/{sid}", headers=_bearer(key))
    assert res.status_code == 204, res.text
    row = _row(lc, sid)
    assert row.status == SOURCE_DISCONNECTED and row.credentials_encrypted is None
    assert len(_leads(lc)) == 1
    assert lgraph.page_fields == ["messages"]  # omnichannel's field kept, leadgen gone
    (ev,) = [e for e in _events(posts, "source.updated") if e["data"]["change"] == "disconnected"]
    assert ev["data"]["status"] == SOURCE_DISCONNECTED
    # a second DELETE is a no-op, the webhook no longer routes to it
    assert client.delete(f"/lead-capture/sources/{sid}", headers=headers).status_code == 204
    db = lc()
    try:
        assert leadgen_service.process_leadgen(db, PAGE_ID, "100000000000555", FORM_ID) == []
    finally:
        db.close()


def test_disconnect_on_a_shared_page_keeps_the_subscription(lc, lgraph):
    from modules.lead_capture.services import source_service

    _second_tenant(lc, True)
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        a = connect_service.connect_facebook(db, DEFAULT_TENANT_ID, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        a_id, b_id = a.id, b.id
        lgraph.calls.clear()
        source_service.disconnect(db, DEFAULT_TENANT_ID, a_id, actor=source_service.Actor.system())
    finally:
        db.close()
    assert "leadgen" in lgraph.page_fields
    assert not any(c.url.path.endswith("/subscribed_apps") and c.method != "GET" for c in lgraph.calls)
    db = lc()
    try:
        created = leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert len(created) == 1 and {lead.source_id for lead in _leads(lc)} == {b_id}
    db = lc()
    try:
        source_service.disconnect(db, TENANT_B, b_id, actor=source_service.Actor.system())
    finally:
        db.close()
    assert lgraph.page_fields == ["messages"]


def test_disconnect_with_a_dead_token_still_disconnects(client, lc, lgraph, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    lgraph.dead = True
    assert client.delete(f"/lead-capture/sources/{sid}", headers=headers).status_code == 204
    row = _row(lc, sid)
    assert row.status == SOURCE_DISCONNECTED and row.credentials_encrypted is None
    assert PAGE_TOKEN not in caplog.text


# ── history (standing rule) ─────────────────────────────────────────────────

def test_history_records_connect_forms_change_disconnect_with_who(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID]}, headers=headers)
    _connect(client, headers)
    client.delete(f"/api/v1/lead-capture/sources/{sid}", headers=_bearer(key))
    for res in (
        client.get(f"/lead-capture/sources/{sid}/history", headers=headers),
        client.get(f"/api/v1/lead-capture/sources/{sid}/history", headers=_bearer(key)),
    ):
        assert res.status_code == 200, res.text
        items = res.json()["data"]
        actions = [i["action"] for i in items]
        assert actions == ["disconnected", "reconnected", "forms_changed", "connected"]  # newest first
        forms = items[2]
        assert forms["from"] == "All forms" and forms["to"] == f"Only {FORM_ID}"
        assert forms["actor"]["type"] == "user" and forms["actor"]["name"]
        assert items[0]["actor"] == {"type": "key", "name": "EcoHub"}
        assert items[0]["from"] == SOURCE_WAITING_FOR_TEST and items[0]["to"] == SOURCE_DISCONNECTED
        assert all(i["createdAt"].endswith("Z") for i in items)
        assert PAGE_TOKEN not in res.text


def test_needs_reconnect_is_in_history_as_system(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    items = client.get(f"/lead-capture/sources/{sid}/history", headers=headers).json()["data"]
    assert items[0]["action"] == "needs_reconnect" and items[0]["actor"]["type"] == "system"


# ── L-A gaps folded in (owner 17 Nov) ───────────────────────────────────────

def test_test_lead_cooldown_is_429_per_form(client, lc, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "environment", "development")
    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    first = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=_bearer(key))
    assert first.status_code == 202, first.text
    again = client.post(f"/api/v1/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=_bearer(key))
    assert again.status_code == 429 and again.json()["error"]["code"] == "test_lead_cooldown"
    assert 1 <= int(again.headers["Retry-After"]) <= 60
    staff = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert staff.status_code == 429 and staff.json()["detail"]["code"] == "test_lead_cooldown"
    assert int(staff.headers["Retry-After"]) >= 1
    assert len(_leads(lc)) == 1  # the refused calls sent nothing
    # another form is not held back
    other = client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID2}, headers=headers)
    assert other.status_code == 202
    # once the cooldown passed it goes through
    db = lc()
    try:
        row = db.get(LcSource, sid)
        reqs = dict(row.config_json["testLeadRequests"])
        reqs[FORM_ID] = (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat()
        row.config_json = {**row.config_json, "testLeadRequests": reqs}
        db.commit()
    finally:
        db.close()
    assert client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": FORM_ID},
                       headers=headers).status_code == 202


def test_shared_page_test_lead_flips_only_the_source_that_asked(client, lc, lgraph):
    """L-A gap (b): tenant A asks for the test lead; Meta's lead reaches the
    whole Page; only A passes its test, B keeps waiting."""
    _second_tenant(lc, True)
    lgraph.test_ids = [LEAD_ID]
    lgraph.lead = {k: v for k, v in lgraph.lead.items() if k != "ad_id"}
    db = lc()
    try:
        connect_service.set_allow_shared_pages(db, DEFAULT_TENANT_ID, True, None)
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b_id = b.id
    finally:
        db.close()
    headers = _login(client)
    a_id = _source_id(client, headers)

    def test_leads(request):
        if request.url.path.endswith(f"/{FORM_ID}/test_leads"):
            lgraph.calls.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"data": []} if not lgraph.sent else {"data": [{"id": LEAD_ID}]})
            lgraph.sent = True
            return httpx.Response(200, json={"id": LEAD_ID})
        return LbGraph.handler(lgraph, request)

    lgraph.sent = False
    lgraph.handler = test_leads
    res = client.post(f"/lead-capture/sources/{a_id}/test-lead", json={"formId": FORM_ID}, headers=headers)
    assert res.status_code == 202, res.text
    assert _signed_webhook(client, _fixture("leadgen-webhook-test-lead.json")).status_code == 200
    assert len(_leads(lc)) == 2  # both products receive Meta's lead, marked test
    assert all(lead.is_test for lead in _leads(lc))
    assert _row(lc, a_id).status == SOURCE_LIVE
    assert _row(lc, b_id).status == SOURCE_WAITING_FOR_TEST


def test_no_token_in_logs_across_lb_flows(client, lc, lgraph, posts, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    sid = _source_id(client, headers)
    _age_source(lc, sid)
    lgraph.form_leads[FORM_ID] = [_lead_body(MISSED_LEAD, FORM_ID, datetime.now(timezone.utc) - timedelta(hours=1))]
    client.get(f"/lead-capture/sources/{sid}/forms", headers=headers)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID]}, headers=headers)
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    lgraph.dead = True
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    lgraph.dead = False
    _connect(client, headers)
    client.delete(f"/lead-capture/sources/{sid}", headers=headers)
    for secret in (PAGE_TOKEN, SYSTEM_TOKEN):
        assert secret not in caplog.text
    db = lc()
    try:
        for lead in db.query(LcLead).all():
            assert PAGE_TOKEN not in json.dumps(lead.attribution_json or {})
    finally:
        db.close()


def test_lb_migration_is_additive_and_fits():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1]
            / "modules/lead_capture/alembic/versions/0004_lc_source_backfill_history.py").read_text()
    rev = text.split('revision = "', 1)[1].split('"', 1)[0]
    assert len(rev) <= 32 and 'down_revision = "0003_lc_source_routing_unique"' in text
    assert "IF NOT EXISTS" in text and "DROP TABLE" not in text.split("def downgrade", 1)[0]


# ── review round 1 ──────────────────────────────────────────────────────────

def _many(form_id: str, count: int, start: datetime, step=timedelta(minutes=20), base=200):
    return [_lead_body(str(100000000000000 + base + i), form_id, start + i * step, email=f"m{i}@example.com")
            for i in range(count)]


def test_backfill_with_more_leads_than_one_read_still_gets_all(client, lc, lgraph, monkeypatch):
    """A form with more leads than one capped read: the window is split, so
    every lead is stored and nothing is read twice into a duplicate."""
    from modules.lead_capture import meta_leads

    monkeypatch.setattr(meta_leads, "PAGE_SIZE", 2)
    monkeypatch.setattr(meta_leads, "MAX_PAGES", 1)
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid, days=1)
    lgraph.form_leads[FORM_ID] = _many(FORM_ID, 7, datetime.now(timezone.utc) - timedelta(hours=5))
    assert client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers).status_code == 202
    assert len(_leads(lc)) == 7
    assert _row(lc, sid).backfill_last_error is None


def test_backfill_cut_by_the_run_budget_continues_next_run(client, lc, lgraph, monkeypatch):
    from modules.lead_capture import meta_leads
    from modules.lead_capture.services import backfill_service

    monkeypatch.setattr(meta_leads, "PAGE_SIZE", 2)
    monkeypatch.setattr(meta_leads, "MAX_PAGES", 1)
    monkeypatch.setattr(backfill_service, "RUN_PAGE_BUDGET", 5)
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid, days=1)
    lgraph.form_leads[FORM_ID] = _many(FORM_ID, 7, datetime.now(timezone.utc) - timedelta(hours=5))
    seen = []
    for _ in range(10):
        db = lc()
        try:
            backfill_service.backfill_source(db, sid)
        finally:
            db.close()
        seen.append(len(_leads(lc)))
        if seen[-1] == 7:
            break
    assert seen[-1] == 7 and seen[0] < 7  # progress across runs, never stuck
    assert len({lead.platform_lead_id for lead in _leads(lc)}) == 7


def test_one_failing_form_does_not_stall_the_others(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid)
    client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": [FORM_ID3, FORM_ID]},
               headers=headers)
    lgraph.form_errors[FORM_ID3] = 100  # e.g. a ticked form deleted on Facebook
    lgraph.form_leads[FORM_ID] = [_lead_body(MISSED_LEAD, FORM_ID, datetime.now(timezone.utc) - timedelta(hours=1))]
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert [lead.platform_lead_id for lead in _leads(lc)] == [MISSED_LEAD]
    row = _row(lc, sid)
    assert row.status == SOURCE_LIVE and row.backfill_last_error and FORM_ID3 in row.backfill_last_error


def test_a_form_level_permission_error_in_backfill_does_not_flip(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    _age_source(lc, sid)
    lgraph.form_errors[FORM_ID] = 200  # Leads Access Manager: this form only
    client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers)
    assert _row(lc, sid).status == SOURCE_LIVE and _mails(lc) == []


def test_a_forms_change_during_ingest_is_not_overwritten(client, lc, lgraph):
    """The ingest caches the form name in config_json; a forms choice saved
    while it read from Meta must survive its commit."""
    headers = _login(client)
    sid = _source_id(client, headers)
    orig = lgraph.handler

    def handler(request):
        if request.url.path.endswith(f"/{FORM_ID}") and request.url.params.get("fields") == "name":
            db = lc()
            try:
                row = db.get(LcSource, sid)
                row.config_json = {**(row.config_json or {}), "formsMode": "pick", "formIds": [FORM_ID]}
                db.commit()
            finally:
                db.close()
        return orig(request)

    lgraph.handler = handler
    db = lc()
    try:
        assert len(leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)) == 1
    finally:
        db.close()
    config = _row(lc, sid).config_json
    assert config["formsMode"] == "pick" and config["formIds"] == [FORM_ID]
    assert config["formNames"][FORM_ID]


@pytest.mark.parametrize("code", [10, 200])
def test_caller_driven_reads_flip_only_on_a_dead_token(client, lc, lgraph, code):
    """A viewer opening the forms list, or a made-up form id on the test lead,
    must not stop a healthy source on a permission-style answer."""
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    lgraph.dead, lgraph.dead_code = True, code
    assert client.get(f"/lead-capture/sources/{sid}/forms", headers=headers).status_code == 400
    assert client.get(f"/lead-capture/sources/{sid}/forms/{FORM_ID}/questions", headers=headers).status_code == 400
    assert _row(lc, sid).status == SOURCE_LIVE and _mails(lc) == []


def test_caller_driven_read_with_a_dead_token_flips(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    lgraph.dead = True  # 190
    res = client.get(f"/lead-capture/sources/{sid}/forms", headers=headers)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "token_invalid"
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT


def test_backfill_run_now_cooldown_and_in_flight_skip(client, lc, lgraph):
    from modules.lead_capture.services import backfill_service

    headers = _login(client)
    sid = _source_id(client, headers)
    key = _key(client, headers)
    assert client.post(f"/lead-capture/sources/{sid}/backfill", headers=headers).status_code == 202
    again = client.post(f"/api/v1/lead-capture/sources/{sid}/backfill", headers=_bearer(key))
    assert again.status_code == 429 and again.json()["error"]["code"] == "backfill_cooldown"
    assert 1 <= int(again.headers["Retry-After"]) <= 60
    # a run already in flight is skipped by the tick (no Graph call)
    _set(lc, sid, backfill_started_at=datetime.now(timezone.utc), backfill_last_run_at=None)
    lgraph.calls.clear()
    db = lc()
    try:
        backfill_service.run_due(db)
    finally:
        db.close()
    assert not any(c.url.path.endswith("/leadgen_forms") for c in lgraph.calls)
    # a stale claim (a crashed worker) does not block for ever
    _set(lc, sid, backfill_started_at=datetime.now(timezone.utc) - timedelta(hours=2))
    db = lc()
    try:
        backfill_service.run_due(db)
    finally:
        db.close()
    assert any(c.url.path.endswith("/leadgen_forms") for c in lgraph.calls)
    assert _row(lc, sid).backfill_started_at is None


def test_reconnect_rechecks_sharing_when_another_product_joined_meanwhile(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT
    lgraph.dead = False
    _second_tenant(lc, True)  # B allows sharing; A (default) does not
    db = lc()
    try:
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
    finally:
        db.close()
    res = _connect(client, headers)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PAGE_IN_USE"
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT


def test_history_never_shows_an_email(client, lc, lgraph):
    from app.models.user import User

    headers = _login(client)
    sid = _source_id(client, headers)
    db = lc()
    try:
        for user in db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).all():
            user.name = ""
        db.commit()
    finally:
        db.close()
    key = _key(client, headers)
    res = client.get(f"/api/v1/lead-capture/sources/{sid}/history", headers=_bearer(key))
    assert res.status_code == 200
    assert "@" not in res.text and res.json()["data"][0]["actor"]["name"] == "Team member"


def test_form_ids_are_capped(client, lc, lgraph):
    headers = _login(client)
    sid = _source_id(client, headers)
    res = client.put(f"/lead-capture/sources/{sid}/forms", json={"formsMode": "pick", "formIds": ["1" * 5000]},
                     headers=headers)
    assert res.status_code == 422


def test_test_lead_requests_are_capped_per_source(client, lc, monkeypatch):
    """Rotating made-up form ids cannot get round the cooldown."""
    from app.config import settings
    from modules.lead_capture.services import form_service

    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(form_service, "_dev_test_lead", lambda source, form_id: None)
    headers = _login(client)
    sid = _source_id(client, headers)
    codes = [
        client.post(f"/lead-capture/sources/{sid}/test-lead", json={"formId": str(400000000000100 + i)},
                    headers=headers).status_code
        for i in range(form_service.TEST_LEADS_PER_HOUR + 1)
    ]
    assert codes[:-1] == [202] * form_service.TEST_LEADS_PER_HOUR and codes[-1] == 429


def test_reconnect_email_subject_has_no_line_breaks(client, lc, lgraph, posts):
    headers = _login(client)
    sid = _source_id(client, headers)
    _set(lc, sid, status=SOURCE_LIVE, account_name="Evil\r\nBcc: x@example.com")
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    (mail,) = _mails(lc)
    assert "\r" not in mail.subject and "\n" not in mail.subject


def test_reconnect_rechecks_sharing_when_another_product_revived_an_old_row(client, lc, lgraph):
    """Security re-check M3: B's old disconnected row (old created_at) is
    revived while A is away; A's reconnect must still face the sharing rule."""
    _second_tenant(lc, True)
    db = lc()
    try:
        b = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        b_id = b.id
        from modules.lead_capture.services import source_service

        source_service.disconnect(db, TENANT_B, b_id, actor=source_service.Actor.system())
    finally:
        db.close()
    _set(lc, b_id, created_at=datetime.now(timezone.utc) - timedelta(days=30))
    headers = _login(client)
    sid = _source_id(client, headers)  # A alone on the Page (B disconnected)
    _set(lc, sid, status=SOURCE_LIVE)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    assert _row(lc, sid).status == SOURCE_NEEDS_RECONNECT
    lgraph.dead = False
    db = lc()
    try:
        revived = connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
        assert revived.id == b_id
    finally:
        db.close()
    res = _connect(client, headers)  # A does not allow sharing
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PAGE_IN_USE"


def test_reconnect_without_a_known_leave_time_checks_sharing(client, lc, lgraph):
    _second_tenant(lc, True)
    headers = _login(client)
    sid = _source_id(client, headers)
    db = lc()
    try:
        row = db.get(LcSource, sid)
        row.status = SOURCE_NEEDS_RECONNECT
        row.config_json = {k: v for k, v in (row.config_json or {}).items() if k != "leftRoutingAt"}
        db.commit()
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
    finally:
        db.close()
    res = _connect(client, headers)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PAGE_IN_USE"


# ── product-scoped API door for connect / reconnect (owner 17 Nov 19:32) ────

def test_connect_and_reconnect_over_the_gateway_key(client, lc, lgraph, caplog):
    caplog.set_level(logging.DEBUG)
    headers = _login(client)
    key = _key(client, headers)
    body = {"pageId": PAGE_ID, "systemUserToken": SYSTEM_TOKEN, "formsMode": "all"}
    res = client.post("/api/v1/lead-capture/sources/facebook", json=body, headers=_bearer(key))
    assert res.status_code == 201, res.text
    sid = res.json()["id"]
    assert res.json()["status"] == SOURCE_WAITING_FOR_TEST and lgraph.page_fields == ["messages", "leadgen"]
    assert SYSTEM_TOKEN not in res.text and PAGE_TOKEN not in res.text
    # broken, then reconnected through the same door: same source
    _set(lc, sid, status=SOURCE_LIVE)
    lgraph.dead = True
    db = lc()
    try:
        with pytest.raises(Exception):
            leadgen_service.process_leadgen(db, PAGE_ID, LEAD_ID, FORM_ID)
    finally:
        db.close()
    lgraph.dead = False
    again = client.post("/api/v1/lead-capture/sources/facebook", json=body, headers=_bearer(key))
    assert again.status_code == 201 and again.json()["id"] == sid and again.json()["status"] == SOURCE_LIVE
    hist = client.get(f"/api/v1/lead-capture/sources/{sid}/history", headers=_bearer(key)).json()["data"]
    assert hist[0]["action"] == "reconnected" and hist[0]["actor"] == {"type": "key", "name": "EcoHub"}
    assert SYSTEM_TOKEN not in caplog.text and PAGE_TOKEN not in caplog.text


def test_gateway_connect_errors_use_the_envelope(client, lc, lgraph):
    headers = _login(client)
    key = _key(client, headers)
    bad = client.post("/api/v1/lead-capture/sources/facebook",
                      json={"pageId": "abc", "systemUserToken": SYSTEM_TOKEN}, headers=_bearer(key))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_page_id"
    _second_tenant(lc, False)
    db = lc()
    try:
        connect_service.connect_facebook(db, TENANT_B, page_id=PAGE_ID, system_user_token=SYSTEM_TOKEN)
    finally:
        db.close()
    res = client.post("/api/v1/lead-capture/sources/facebook",
                      json={"pageId": PAGE_ID, "systemUserToken": SYSTEM_TOKEN}, headers=_bearer(key))
    assert res.status_code == 409 and res.json()["error"]["code"] == "PAGE_IN_USE"
    assert TENANT_B not in res.text
