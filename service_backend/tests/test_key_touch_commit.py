"""Plan 50 follow-up: a key request holds nothing open once the auth
dependency has returned, and the AC-49-02 transaction check looks only at
the media host, so it cannot be tripped by the limiter's own redis client
(which resolves its own host name while the key lookup's read transaction is
still open).
"""
from starlette.requests import Request

from modules.omnichannel import api_auth
from tests.test_key_url_check_first import _Rig
from tests.test_omnichannel_send_route_limits import (
    MEDIA_HOST,
    _PATHS,
    _install,
    _pdf_media,
    _setup,
)
import pytest


def _request():
    return Request({"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b""})


def test_key_request_session_is_clean_once_auth_dependency_returns(client, session_factory):
    """After `get_api_workspace` yields: no pending write, no open transaction
    on the request session, and `last_used_at` is already committed."""
    headers, _cid, _ch = _setup(client, session_factory, phone="+60500000001", token="tkn-50")
    db = session_factory()
    try:
        gen = api_auth.get_api_workspace(_request(), headers["Authorization"], db)
        workspace = next(gen)
        assert workspace.key_id
        assert not (db.new or db.dirty or db.deleted), "pending write left on the request session"
        assert not db.in_transaction(), "request session still holds a transaction after the auth dependency"
        gen.close()
    finally:
        db.close()
    check = session_factory()
    try:
        from modules.omnichannel.models import WorkspaceApiKey

        row = check.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == workspace.key_id).one()
        assert row.last_used_at is not None
    finally:
        check.close()


@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_49_02_media_host_check_holds_no_transaction_deterministic(
    client, session_factory, monkeypatch, path
):
    """Same claim as test_key_url_check_first AC-49-02, but only a lookup of
    the media host counts as the URL check; the limiter's redis connect (a
    random host name) is ignored. Must also have seen the media host."""
    phone = "+60500000002" if path == "media" else "+60500000003"
    headers, _cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-50b")
    _install(monkeypatch, media=_pdf_media)
    rig = _Rig()
    rig.attach(monkeypatch)
    seen = []
    inner = None
    try:
        import app.services.url_guard as guard

        inner = guard.socket.getaddrinfo

        def media_only(host, *a, **k):
            if host == MEDIA_HOST:
                seen.append([s for s in list(rig._open) if s.in_transaction()])
            return inner(host, *a, **k)

        monkeypatch.setattr(guard.socket, "getaddrinfo", media_only)
        url, body = _PATHS[path](phone)
        res = client.post(url, json=body, headers=headers)
        assert res.status_code in (200, 201, 202), res.text
        assert seen, "the media host was never resolved (test would pass for the wrong reason)"
        assert all(held == [] for held in seen), (
            f"{len(seen[0])} session(s) in a transaction while {MEDIA_HOST} was resolved"
        )
    finally:
        rig.detach()
