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
