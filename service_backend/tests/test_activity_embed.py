"""Embed-session activity logging (sprint-4/12 Slice 3, AC-DLC-20).

``EmbedSessionService.exchange()`` records ONE ``embed_session`` integration_activity
row on success AND on each typed ``EmbedError`` (with the error code as the row's
error_code), attributed to the connection's tenant, capturing the parent origin,
and NEVER storing the raw assertion / embedSecret. A failure so early there's no
resolvable tenant (unknown issuer) records nothing.
"""
import time
import uuid

from app.models.integration_activity import (
    IntegrationActivity,
    SOURCE_EMBED_SESSION,
)
from tests.conftest import DEFAULT_TENANT_ID
from tests.test_omnichannel_embed import (
    ORIGIN,
    OTHER_ORIGIN,
    SECRET_A,
    _assertion,
    _exchange,
    _make_connection,
    _workspace_id,
)


def _embed_rows(session_factory):
    db = session_factory()
    rows = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.source == SOURCE_EMBED_SESSION)
        .all()
    )
    # Detach a plain snapshot so the caller can read after the session closes.
    out = [
        {
            "tenant_id": r.tenant_id,
            "status": r.status,
            "status_code": r.status_code,
            "operation": r.operation,
            "error_code": r.error_code,
            "workspace_id": r.workspace_id,
            "request": r.request_summary_json,
        }
        for r in rows
    ]
    db.close()
    return out


# ── success ──────────────────────────────────────────────────────────────────
def test_embed_success_records_row(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(client, _assertion(iss=cid, workspace_id=wid, email="a@x.io"))
    assert res.status_code == 200, res.text

    rows = _embed_rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == DEFAULT_TENANT_ID
    assert row["status"] == "success"
    assert row["status_code"] == 200
    assert row["operation"] == "embed:session"
    assert row["workspace_id"] == wid
    # Parent origin captured; NO raw assertion / embedSecret stored anywhere.
    assert row["request"] == {"parentOrigin": ORIGIN}
    assert SECRET_A not in str(row)


# ── each typed EmbedError → error row with the code ──────────────────────────
def test_embed_bad_signature_records_invalid_assertion(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(
        client,
        _assertion(iss=cid, workspace_id=wid, secret="the-wrong-secret-value-123456"),
    )
    assert res.status_code == 401
    rows = _embed_rows(session_factory)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["error_code"] == "invalid_assertion"
    assert rows[0]["status_code"] == 401
    assert rows[0]["tenant_id"] == DEFAULT_TENANT_ID


def test_embed_expired_records_expired(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    now = int(time.time())
    res = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, iat=now - 2000, exp=now - 1000)
    )
    assert res.status_code == 401
    rows = _embed_rows(session_factory)
    assert rows and rows[0]["error_code"] == "expired"


def test_embed_origin_not_allowed_records_code(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(
        client, _assertion(iss=cid, workspace_id=wid), origin=OTHER_ORIGIN
    )
    assert res.status_code == 403
    rows = _embed_rows(session_factory)
    assert rows and rows[0]["error_code"] == "origin_not_allowed"
    assert rows[0]["status_code"] == 403


def test_embed_workspace_not_found_records_code(client, session_factory):
    cid = _make_connection(session_factory)
    res = _exchange(
        client, _assertion(iss=cid, workspace_id="not-this-tenants-workspace")
    )
    assert res.status_code == 404
    rows = _embed_rows(session_factory)
    assert rows and rows[0]["error_code"] == "workspace_not_found"
    assert rows[0]["status_code"] == 404


def test_embed_replayed_records_code(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    jti = str(uuid.uuid4())
    a = _assertion(iss=cid, workspace_id=wid, jti=jti)
    assert _exchange(client, a).status_code == 200
    assert _exchange(client, a).status_code == 401  # replay
    rows = _embed_rows(session_factory)
    # Two rows: one success + one replayed error.
    codes = sorted(r["error_code"] or "success" for r in rows)
    assert codes == ["replayed", "success"]


# ── unattributable failure (unknown issuer) → NO row ─────────────────────────
def test_embed_unknown_issuer_records_nothing(client, session_factory):
    wid = _workspace_id(session_factory)
    res = _exchange(client, _assertion(iss="no-such-connection", workspace_id=wid))
    assert res.status_code == 401
    # No connection → no resolvable tenant → nothing logged (documented skip).
    assert _embed_rows(session_factory) == []
