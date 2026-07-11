"""Integration-activity log tests (sprint-4/12 Slice 1).

Covers the write seam (failure isolation, tenant-skip), redaction (secrets
masked, message content kept), tenant-scoped reads, and the read endpoints
(camelCase wire + permission gating).
"""
from app.activity_log.redaction import redact
from app.activity_log.service import ActivityLogService
from app.models.integration_activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    SOURCE_INBOUND_API,
    IntegrationActivity,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, DEFAULT_TENANT_ID

OTHER_TENANT = "tenant-other-xyz"


def _demo_headers(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── AC-DLC-04 / AC-DLC-25: redaction ────────────────────────────────────────


def test_redact_masks_secrets_keeps_message_text():
    payload = {
        "Authorization": "Bearer fxw_live_supersecrettoken",
        "apiKey": "fxw_live_abc123",
        "api_key": "fxw_live_def456",
        "access_token": "meta_tok_xyz",
        "embedSecret": "shhh",
        "password": "hunter2",
        "assertion": "eyJ.jwt.sig",
        "nested": {"clientSecret": "zzz", "message": "Hello from WhatsApp"},
        "list": [{"token": "t1"}, {"text": "keep me"}],
        "message": "Order #42 shipped",
    }
    out = redact(payload)
    assert out["Authorization"] == "***"
    assert out["apiKey"] == "***"
    assert out["api_key"] == "***"
    assert out["access_token"] == "***"
    assert out["embedSecret"] == "***"
    assert out["password"] == "***"
    assert out["assertion"] == "***"
    assert out["nested"]["clientSecret"] == "***"
    # Message CONTENT is not a secret key → preserved.
    assert out["nested"]["message"] == "Hello from WhatsApp"
    assert out["message"] == "Order #42 shipped"
    assert out["list"][0]["token"] == "***"
    assert out["list"][1]["text"] == "keep me"
    # No plaintext key leaks anywhere in the redacted structure.
    assert "supersecrettoken" not in str(out)
    assert "fxw_live_abc123" not in str(out)


# ── AC-DLC-02 / AC-DLC-05: writer never raises ──────────────────────────────


def test_record_swallows_a_raising_writer(session_factory, monkeypatch):
    db = session_factory()
    service = ActivityLogService(db)

    def _boom(*_a, **_k):
        raise RuntimeError("db exploded")

    # Force the insert to raise — record() must swallow, never propagate.
    monkeypatch.setattr(service.repo, "add", _boom)
    result = service.record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status=ACTIVITY_SUCCESS,
    )
    assert result is None  # swallowed, not raised
    db.close()


def test_record_skips_when_no_tenant(session_factory):
    db = session_factory()
    result = ActivityLogService(db).record(
        tenant_id=None,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status=ACTIVITY_SUCCESS,
    )
    assert result is None
    assert db.query(IntegrationActivity).count() == 0
    db.close()


def test_record_writes_and_redacts_error_and_request(session_factory):
    db = session_factory()
    row = ActivityLogService(db).record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status=ACTIVITY_ERROR,
        status_code=401,
        error_code="401",
        error_message="denied",
        latency_ms=12,
        trace_id="trace-1",
        request={"headers": {"authorization": "Bearer fxw_live_zzz"}, "path": "/x"},
    )
    assert row is not None
    fetched = db.query(IntegrationActivity).filter_by(id=row.id).one()
    assert fetched.tenant_id == DEFAULT_TENANT_ID
    assert fetched.request_summary_json["headers"]["authorization"] == "***"
    assert fetched.request_summary_json["path"] == "/x"
    assert "fxw_live_zzz" not in str(fetched.request_summary_json)
    db.close()


# ── AC-DLC-01: tenant scoping on reads ──────────────────────────────────────


def test_read_is_tenant_scoped(session_factory):
    db = session_factory()
    svc = ActivityLogService(db)
    mine = svc.record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status=ACTIVITY_SUCCESS,
    )
    other = svc.record(
        tenant_id=OTHER_TENANT,
        source=SOURCE_INBOUND_API,
        operation="POST /other",
        status=ACTIVITY_SUCCESS,
    )
    rows, total = svc.list(DEFAULT_TENANT_ID)
    ids = {r.id for r in rows}
    assert mine.id in ids
    assert other.id not in ids
    assert total == 1
    # Cross-tenant detail read returns nothing.
    assert svc.get(DEFAULT_TENANT_ID, other.id) is None
    assert svc.get(DEFAULT_TENANT_ID, mine.id) is not None
    db.close()


def test_list_filter_by_source_and_status(session_factory):
    db = session_factory()
    svc = ActivityLogService(db)
    svc.record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="ok",
        status=ACTIVITY_SUCCESS,
    )
    svc.record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="bad",
        status=ACTIVITY_ERROR,
    )
    fg = {
        "kind": "group",
        "combinator": "and",
        "rules": [{"kind": "condition", "field": "status", "operator": "eq", "value": "error"}],
    }
    from app.schemas.filters import FilterGroup

    rows, total = svc.list(DEFAULT_TENANT_ID, filter_group=FilterGroup.model_validate(fg))
    assert total == 1
    assert rows[0].operation == "bad"
    db.close()


# ── AC-DLC-06/07/08: endpoints (camelCase + permission gated) ───────────────


def test_list_endpoint_camelcase_and_gated(client, session_factory):
    db = session_factory()
    ActivityLogService(db).record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_INBOUND_API,
        operation="POST /messages",
        status=ACTIVITY_SUCCESS,
        status_code=200,
        latency_ms=7,
        trace_id="trace-42",
    )
    db.close()

    # Unauthenticated → 401 (permission gated).
    assert client.get("/integration-logs").status_code == 401

    headers = _demo_headers(client)
    res = client.get("/integration-logs", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    item = body["data"][0]
    assert item["source"] == "inbound_api"
    assert item["statusCode"] == 200
    assert item["latencyMs"] == 7
    assert item["traceId"] == "trace-42"
    assert item["createdAt"].endswith("Z")

    # Detail
    detail = client.get(f"/integration-logs/{item['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["operation"] == "POST /messages"

    # Unknown id → 404
    assert client.get("/integration-logs/nope", headers=headers).status_code == 404


def test_detail_endpoint_gated(client):
    assert client.get("/integration-logs/anything").status_code == 401


# ── Body capture (enhancement): tee request + response bodies safely ────────


def test_summarize_body_json_parsed():
    from app.activity_log.middleware import _summarize_body

    raw = b'{"to":"+60","type":"text","text":{"body":"hi"}}'
    out = _summarize_body(
        raw, content_type="application/json", total_size=len(raw), is_json=True, truncated=False
    )
    assert out == {"to": "+60", "type": "text", "text": {"body": "hi"}}


def test_summarize_body_multipart_stores_note_not_bytes():
    from app.activity_log.middleware import _summarize_body

    # Multipart / binary body is NEVER buffered — capture=False, only the size.
    out = _summarize_body(
        b"",  # nothing buffered (capture was off)
        content_type="multipart/form-data; boundary=xyz",
        total_size=2048,
        is_json=False,
        truncated=False,
    )
    assert out == {"note": "multipart/form-data body (2048 bytes) not captured"}


def test_summarize_body_oversize_truncates():
    from app.activity_log.middleware import _summarize_body

    capped = b'{"blob":"' + b"a" * 16 * 1024  # a JSON body clipped at the cap
    out = _summarize_body(
        capped,
        content_type="application/json",
        total_size=64 * 1024,
        is_json=True,
        truncated=True,
    )
    assert out["truncated"] is True
    assert out["raw"].startswith('{"blob":"aaaa')


def test_summarize_body_none_when_empty():
    from app.activity_log.middleware import _summarize_body

    assert (
        _summarize_body(b"", content_type=None, total_size=0, is_json=False, truncated=False)
        is None
    )


def test_gateway_send_captures_request_and_response_bodies(client, session_factory):
    """A JSON POST /messages through the gateway records the inbound_api row with
    the REQUEST body (secret Authorization header masked, message text kept) AND
    the RESPONSE body — the 'No payload captured' case is gone for JSON."""
    from app.models.integration_activity import IntegrationActivity
    from tests.test_omnichannel_api_gateway import (
        _default_workspace_id,
        _mint,
        _seed_channel,
        _seed_open_contact,
    )

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60123123123", open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    res = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123123123", "type": "text", "text": {"body": "Order #42 shipped"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 202, res.text

    db = session_factory()
    try:
        row = (
            db.query(IntegrationActivity)
            .filter(
                IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
                IntegrationActivity.source == SOURCE_INBOUND_API,
                IntegrationActivity.operation.like("%/messages"),
            )
            .one()
        )
    finally:
        db.close()

    req = row.request_summary_json
    assert req is not None
    # Secret KEY masked, message CONTENT preserved.
    assert req["headers"]["authorization"] == "***"
    assert req["body"]["text"]["body"] == "Order #42 shipped"
    assert "Bearer" not in str(req["headers"]["authorization"])
    # Response body captured (the 202 send envelope), no longer "No payload".
    assert row.response_summary_json is not None
    assert row.response_summary_json["body"]["status"] == "queued"
