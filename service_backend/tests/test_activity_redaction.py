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
