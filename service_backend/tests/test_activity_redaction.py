"""Redaction matrix (sprint-4/12 Slice 3, AC-DLC-25).

Proves every secret shape - API key, bearer token, ``embedSecret``, Meta access
token - is masked across the FOUR sources' request/response summaries, while
WhatsApp message CONTENT is preserved (it's needed to troubleshoot). The matrix
drives real ``ActivityLogService.record`` writes (one per source) and asserts the
STORED summary carries no plaintext secret.
"""
from app.activity_log.redaction import redact
from app.activity_log.service import ActivityLogService
from app.models.integration_activity import (
    IntegrationActivity,
    SOURCE_EMBED_SESSION,
    SOURCE_INBOUND_API,
    SOURCE_OUTBOUND_META,
    SOURCE_WEBHOOK_DELIVERY,
)
from tests.conftest import DEFAULT_TENANT_ID

# The four secret shapes the matrix must mask, and one message body it must keep.
API_KEY = "fxw_live_apikey_abcdef123456"
BEARER = "Bearer fxw_live_bearer_zyxwvu987654"
EMBED_SECRET = "embed-secret-supersecret-000111"
META_TOKEN = "EAAG_meta_access_token_998877"
MESSAGE = "Order #42 shipped - track at example.com"


def _summary() -> dict:
    """A summary carrying EVERY secret key shape + a message body to keep."""
    return {
        "headers": {"authorization": BEARER, "content-type": "application/json"},
        "apiKey": API_KEY,
        "api_key": API_KEY,
        "embedSecret": EMBED_SECRET,
        "accessToken": META_TOKEN,
        "access_token": META_TOKEN,
        "nested": {"clientSecret": EMBED_SECRET, "message": MESSAGE},
        "list": [{"token": BEARER}, {"text": "keep me"}],
        "message": MESSAGE,
        "body": {"text": MESSAGE},
    }


def _all_secrets_masked(stored: dict) -> None:
    blob = str(stored)
    assert API_KEY not in blob
    assert "fxw_live_bearer" not in blob
    assert EMBED_SECRET not in blob
    assert META_TOKEN not in blob
    # Message content survives - not a secret KEY.
    assert MESSAGE in blob


# ── pure redactor over the matrix (fast) ─────────────────────────────────────
def test_redaction_matrix_masks_all_secret_shapes():
    out = redact(_summary())
    assert out["headers"]["authorization"] == "***"
    assert out["apiKey"] == "***"
    assert out["api_key"] == "***"
    assert out["embedSecret"] == "***"
    assert out["accessToken"] == "***"
    assert out["access_token"] == "***"
    assert out["nested"]["clientSecret"] == "***"
    assert out["list"][0]["token"] == "***"
    # Message content preserved everywhere.
    assert out["nested"]["message"] == MESSAGE
    assert out["message"] == MESSAGE
    assert out["body"]["text"] == MESSAGE
    assert out["list"][1]["text"] == "keep me"
    _all_secrets_masked(out)


# ── stored rows across all four sources ──────────────────────────────────────
def test_redaction_matrix_across_all_four_sources(session_factory):
    db = session_factory()
    svc = ActivityLogService(db)
    for source in (
        SOURCE_INBOUND_API,
        SOURCE_EMBED_SESSION,
        SOURCE_OUTBOUND_META,
        SOURCE_WEBHOOK_DELIVERY,
    ):
        row = svc.record(
            tenant_id=DEFAULT_TENANT_ID,
            source=source,
            operation=f"{source}:op",
            status="success",
            request=_summary(),
            response=_summary(),
        )
        assert row is not None, source
        stored = (
            db.query(IntegrationActivity)
            .filter(IntegrationActivity.id == row.id)
            .first()
        )
        # No plaintext secret anywhere in the stored request/response summaries.
        _all_secrets_masked(stored.request_summary_json)
        _all_secrets_masked(stored.response_summary_json)
    db.close()


# ── plan 38 gap 7, AC-38-146: {"key": ..., "value": ...} rows ────────────────
def _kv_summary() -> dict:
    return {
        "headers": [
            {"key": "Authorization", "value": "Bearer kv-secret-1"},
            {"key": "X-Api-Token", "value": "kv-token-2"},
            {"key": "Accept", "value": "application/json"},
        ],
        "body": {
            "config": {
                "headers": [
                    {"key": "X-Client-Secret", "value": "kv-secret-3"},
                    {"key": "Content-Type", "value": "text/plain"},
                ],
                "inner": {"rows": [{"key": "api_key", "value": "kv-secret-4"}, {"key": "Accept", "value": "keep"}]},
            }
        },
    }


def test_ac_38_146_key_value_row_masked(session_factory):
    out = redact(_kv_summary())
    h = out["headers"]
    assert h[0] == {"key": "Authorization", "value": "***"}
    assert h[1] == {"key": "X-Api-Token", "value": "***"}
    assert h[2] == {"key": "Accept", "value": "application/json"}
    nested = out["body"]["config"]
    assert nested["headers"][0] == {"key": "X-Client-Secret", "value": "***"}
    assert nested["headers"][1] == {"key": "Content-Type", "value": "text/plain"}
    assert nested["inner"]["rows"][0] == {"key": "api_key", "value": "***"}
    assert nested["inner"]["rows"][1] == {"key": "Accept", "value": "keep"}
    blob = str(out)
    for secret in ("kv-secret-1", "kv-token-2", "kv-secret-3", "kv-secret-4"):
        assert secret not in blob

    # stored request AND response summaries
    db = session_factory()
    try:
        row = ActivityLogService(db).record(
            tenant_id=DEFAULT_TENANT_ID, source=SOURCE_INBOUND_API, operation="POST /workflows",
            status="success", request=_kv_summary(), response=_kv_summary(),
        )
        stored = db.query(IntegrationActivity).filter(IntegrationActivity.id == row.id).first()
        for summary in (stored.request_summary_json, stored.response_summary_json):
            for secret in ("kv-secret-1", "kv-token-2", "kv-secret-3", "kv-secret-4"):
                assert secret not in str(summary)
            assert summary["headers"][2]["value"] == "application/json"
            assert summary["body"]["config"]["headers"][1]["value"] == "text/plain"
    finally:
        db.close()


# ── plan 38 gap 7 review round 1, AC-38-146: large and unparseable bodies ───────────
def _stored_rows(session_factory, key_id):
    db = session_factory()
    try:
        return [(r.operation, r.request_summary_json, r.response_summary_json)
                for r in db.query(IntegrationActivity).filter(IntegrationActivity.api_key_id == key_id).all()]
    finally:
        db.close()


def test_ac_38_146_big_and_unparseable_bodies_never_store_raw_secrets(client, session_factory):
    import json

    from tests.test_omnichannel_api_gateway import _default_workspace_id
    from tests.test_omnichannel_key_workflows import BASE, _key

    ws = _default_workspace_id(session_factory)
    kid, hdr = _key(client, ws)
    secret = "Bearer s3cr3t-LOG-PROBE"
    definition = {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "entity.shortcut",
             "config": {"entityType": "omnichannel_contact"}},
            {"id": "http_1", "kind": "action", "type": "http.request",
             "config": {"method": "POST", "url": "https://api.example.com/x",
                        "headers": [{"key": "Authorization", "value": secret}],
                        "bodyMode": "text", "body": "y" * 20000}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "http_1"}],
    }
    big = client.post(f"{BASE}/workflows", json={"name": "big", "draftDefinition": definition}, headers=hdr)
    assert big.status_code == 201, big.text

    broken = ('{"name": "x", "draftDefinition": {"headers": [{"key": "Authorization", "value": "%s"}' % secret).encode()
    bad = client.post(f"{BASE}/workflows", content=broken,
                      headers={**hdr, "Content-Type": "application/json"})
    assert bad.status_code == 422, bad.text

    rows = _stored_rows(session_factory, kid)
    assert len(rows) == 2
    for op, req, resp in rows:
        blob = json.dumps(req) + json.dumps(resp)
        assert "s3cr3t-LOG-PROBE" not in blob, f"{op}: the secret reached a stored summary"

    # the unparseable body is stored as a note with its size, never raw text
    unparsed = next(req for op, req, resp in rows if req["body"] is not None and "note" in req["body"]
                    and str(len(broken)) in req["body"]["note"])
    assert "raw" not in unparsed["body"]
    # the over-capture-limit request is a note with its size too
    over = [req for op, req, resp in rows if req["body"] is not None and "note" in req["body"]
            and req is not unparsed]
    assert over and "raw" not in over[0]["body"]
