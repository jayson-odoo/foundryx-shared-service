"""Omnichannel embed host tests - plan 11H (AC-11H-01..11, 18).

Covers /embed/session verify matrix (bad sig / expired / future-iat / wrong-aud /
replay / origin / workspace / rotation), external-agent upsert + cross-consumer
isolation, federated attribution, and access-token scope + caps enforcement -
proving a widget-bypassing direct API call still 403s.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

ORIGIN = "https://consumer.example"
OTHER_ORIGIN = "https://evil.example"
AUD = "omnichannel-embed"
SECRET_A = "embed-secret-alpha-0123456789"
SECRET_B = "embed-secret-bravo-9876543210"


# ── fixtures / helpers ───────────────────────────────────────────────────────
def _native_token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _workspace_id(session_factory) -> str:
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    wid = ws.id
    db.close()
    return wid


def _make_connection(session_factory, *, connection_id=None, secret=SECRET_A, origins=(ORIGIN,)) -> str:
    """Create an ``omnichannel_shared`` connection with an encrypted embedSecret +
    allowedOrigins in plain config. Returns its id (= the assertion ``iss``)."""
    db = session_factory()
    cid = connection_id or str(uuid.uuid4())
    conn = Connection(
        id=cid,
        tenant_id=DEFAULT_TENANT_ID,
        provider="omnichannel_shared",
        type="omnichannel",
        name="EMS embed link",
        config_json={"allowedOrigins": list(origins)},
        credentials_json=encrypt_secret({"embedSecret": secret}),
        status="ACTIVE",
    )
    db.add(conn)
    db.commit()
    db.close()
    return cid


def _seed_contact(session_factory, *, workspace_id, first="Sarah", last="Chen", phone="+60123456789"):
    """Insert a workspace-scoped contact + a dev channel with an OPEN CSW window
    so embed replies land inside the 24h window."""
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    channel = db.query(Channel).filter(Channel.tenant_id == DEFAULT_TENANT_ID).first()
    if channel is None:
        channel = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=workspace_id,
            channel_type="WHATSAPP",
            name="Test WhatsApp",
            credentials_json=encrypt_credentials({"dev": True}),
            phone_number_id="pn-embed",
            display_phone_number="+60 11-111 1111",
            is_active=True,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(channel)
        db.flush()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        first_name=first,
        last_name=last,
        phone=phone,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="HIGH",
        csw_expires_at=datetime.now(timezone.utc) + timedelta(hours=20),
    )
    db.add(contact)
    db.commit()
    cid = contact.id
    db.close()
    return cid


def _assertion(
    *,
    iss,
    workspace_id,
    secret=SECRET_A,
    sub="u-1",
    name="Alice Agent",
    scope="inbox",
    caps=("reply", "assign", "close", "note", "send_template"),
    aud=AUD,
    iat=None,
    exp=None,
    jti=None,
    email=None,
    avatar_url=None,
    alg="HS256",
):
    now = int(time.time())
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "workspaceId": workspace_id,
        "scope": scope,
        "name": name,
        "caps": list(caps),
        "allowedOrigins": [ORIGIN],
        "iat": iat if iat is not None else now,
        "exp": exp if exp is not None else now + 900,
        "jti": jti or str(uuid.uuid4()),
    }
    if email is not None:
        claims["email"] = email
    if avatar_url is not None:
        claims["avatarUrl"] = avatar_url
    return jwt.encode(claims, secret, algorithm=alg)


def _exchange(client, assertion, *, origin=ORIGIN):
    # The widget sends the VALIDATED PARENT origin in the request BODY (contract
    # §3/§5) - NOT the browser Origin header (that is the widget's own
    # shared-service origin). `origin=None` omits it → origin_not_allowed.
    body = {"assertion": assertion}
    if origin is not None:
        body["parentOrigin"] = origin
    return client.post("/embed/session", json=body)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── Slice 2: /embed/session verify + exchange ────────────────────────────────
def test_valid_assertion_exchanges_for_access_token(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(client, _assertion(iss=cid, workspace_id=wid, email="a@x.io"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accessToken"]
    assert body["expiresIn"] == 900
    assert body["agent"]["name"] == "Alice Agent"
    assert body["workspace"]["id"] == wid
    assert body["scope"] == "inbox"
    assert "reply" in body["caps"]
    # No cookie is set (contract §3).
    assert "set-cookie" not in {k.lower() for k in res.headers}


def test_bad_signature_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    a = _assertion(iss=cid, workspace_id=wid, secret="the-wrong-secret-value-123456")
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_expired_assertion_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    now = int(time.time())
    a = _assertion(iss=cid, workspace_id=wid, iat=now - 2000, exp=now - 1000)
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "expired"


def test_future_iat_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    now = int(time.time())
    a = _assertion(iss=cid, workspace_id=wid, iat=now + 3600, exp=now + 4500)
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_wrong_audience_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    a = _assertion(iss=cid, workspace_id=wid, aud="some-other-aud")
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_non_hs256_alg_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    # A token signed HS512 must be rejected at the header check (we only verify HS256).
    a = _assertion(iss=cid, workspace_id=wid, alg="HS512")
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_replayed_jti_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    jti = str(uuid.uuid4())
    a = _assertion(iss=cid, workspace_id=wid, jti=jti)
    first = _exchange(client, a)
    assert first.status_code == 200, first.text
    second = _exchange(client, a)  # same jti
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "replayed"


def test_origin_not_allowed_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(client, _assertion(iss=cid, workspace_id=wid), origin=OTHER_ORIGIN)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "origin_not_allowed"


def test_missing_origin_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    res = _exchange(client, _assertion(iss=cid, workspace_id=wid), origin=None)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "origin_not_allowed"


def test_parent_origin_from_body_not_header(client, session_factory):
    """Finding 2: the check validates the parentOrigin BODY field, and IGNORES the
    browser Origin header (which is the widget's own shared-service origin). A
    valid parentOrigin succeeds even with a foreign Origin header; a valid Origin
    header without a parentOrigin body is refused."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    # Valid parentOrigin body + a foreign/shared-service Origin header → 200.
    ok = client.post(
        "/embed/session",
        json={"assertion": _assertion(iss=cid, workspace_id=wid), "parentOrigin": ORIGIN},
        headers={"Origin": "https://widget.sharedservice.example"},
    )
    assert ok.status_code == 200, ok.text
    # Allowed Origin header but NO parentOrigin body → origin_not_allowed.
    no_body = client.post(
        "/embed/session",
        json={"assertion": _assertion(iss=cid, workspace_id=wid)},
        headers={"Origin": ORIGIN},
    )
    assert no_body.status_code == 403
    assert no_body.json()["error"]["code"] == "origin_not_allowed"


def test_unknown_issuer_rejected(client, session_factory):
    wid = _workspace_id(session_factory)
    a = _assertion(iss="no-such-connection", workspace_id=wid)
    res = _exchange(client, a)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_workspace_mismatch_rejected(client, session_factory):
    cid = _make_connection(session_factory)
    a = _assertion(iss=cid, workspace_id="not-this-tenants-workspace")
    res = _exchange(client, a)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "workspace_not_found"


def test_rotating_embed_secret_invalidates_old_assertions(client, session_factory):
    """Slice 5 / AC-11H-18: rotating embedSecret makes an outstanding assertion
    fail signature."""
    cid = _make_connection(session_factory, secret=SECRET_A)
    wid = _workspace_id(session_factory)
    old = _assertion(iss=cid, workspace_id=wid, secret=SECRET_A)
    # Rotate the connection's embedSecret.
    db = session_factory()
    conn = db.query(Connection).filter(Connection.id == cid).first()
    conn.credentials_json = encrypt_secret({"embedSecret": "rotated-secret-abcdef123456"})
    db.commit()
    db.close()
    res = _exchange(client, old)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


# ── Slice 1: external-agent provisioning + isolation ─────────────────────────
def test_external_agent_upsert_and_refresh(client, session_factory):
    from modules.omnichannel.models import ExternalAgent

    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    r1 = _exchange(client, _assertion(iss=cid, workspace_id=wid, sub="u-1", name="Alice"))
    aid = r1.json()["agent"]["id"]
    # Later assertion refreshes name/email/avatar for the SAME (connection, sub).
    r2 = _exchange(
        client,
        _assertion(iss=cid, workspace_id=wid, sub="u-1", name="Alice Renamed", email="al@x.io"),
    )
    assert r2.json()["agent"]["id"] == aid  # same identity
    assert r2.json()["agent"]["name"] == "Alice Renamed"
    db = session_factory()
    rows = db.query(ExternalAgent).filter(ExternalAgent.sub == "u-1").all()
    assert len(rows) == 1
    assert rows[0].email == "al@x.io"
    db.close()


def test_cross_consumer_identity_isolation(session_factory):
    """Two consumers whose agents share sub='u-1' stay strictly distinct via the
    (connection_id, sub) key - Consumer A's agent can never be Consumer B's.
    (One shared-service tenant holds one omnichannel_shared connection, so the
    two consumers are distinct connections; asserted at the identity layer.)"""
    from modules.omnichannel.models import ExternalAgent
    from modules.omnichannel.services.external_agent_service import ExternalAgentService

    db = session_factory()
    svc = ExternalAgentService(db)
    a = svc.upsert(connection_id="conn-A", tenant_id=DEFAULT_TENANT_ID, sub="u-1", name="A One")
    b = svc.upsert(connection_id="conn-B", tenant_id=DEFAULT_TENANT_ID, sub="u-1", name="B One")
    assert a.id != b.id
    assert db.query(ExternalAgent).filter(ExternalAgent.sub == "u-1").count() == 2
    # Re-upsert A's (conn, sub) returns the SAME row (no third identity).
    a2 = svc.upsert(connection_id="conn-A", tenant_id=DEFAULT_TENANT_ID, sub="u-1", name="A Renamed")
    assert a2.id == a.id
    db.close()


# ── Slice 3: attribution + scope + caps ──────────────────────────────────────
def test_reply_attributed_to_external_agent(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(client, _assertion(iss=cid, workspace_id=wid, name="Alice Agent")).json()["accessToken"]
    send = client.post(
        f"/omnichannel/contacts/{contact_id}/messages",
        json={"body": "Hello from the widget"},
        headers=_bearer(token),
    )
    assert send.status_code == 201, send.text
    body = send.json()
    assert body["senderName"] == "Alice Agent"
    assert body["senderExternalAgentId"]
    assert body["senderId"] is None
    # The list mapper returns the external identity too.
    msgs = client.get(
        f"/omnichannel/contacts/{contact_id}/messages", headers=_bearer(token)
    ).json()
    agent_msgs = [m for m in msgs if m["senderType"] == "AGENT"]
    assert agent_msgs and agent_msgs[-1]["senderName"] == "Alice Agent"


def test_inbox_token_lists_workspace(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(client, _assertion(iss=cid, workspace_id=wid, scope="inbox")).json()["accessToken"]
    res = client.get("/omnichannel/contacts", headers=_bearer(token))
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_thread_scoped_token_cannot_list(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, scope=f"thread:{contact_id}")
    ).json()["accessToken"]
    res = client.get("/omnichannel/contacts", headers=_bearer(token))
    assert res.status_code == 403


def test_thread_scoped_token_cannot_touch_other_contact(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    mine = _seed_contact(session_factory, workspace_id=wid, phone="+60111111111")
    other = _seed_contact(session_factory, workspace_id=wid, phone="+60222222222")
    token = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, scope=f"thread:{mine}")
    ).json()["accessToken"]
    # Own thread OK.
    assert client.get(f"/omnichannel/contacts/{mine}", headers=_bearer(token)).status_code == 200
    # Any other contact → 403 (cannot widen).
    assert client.get(f"/omnichannel/contacts/{other}", headers=_bearer(token)).status_code == 403
    assert (
        client.post(
            f"/omnichannel/contacts/{other}/messages",
            json={"body": "hi"},
            headers=_bearer(token),
        ).status_code
        == 403
    )


def test_read_only_token_refused_on_writes(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, caps=["read_only"])
    ).json()["accessToken"]
    # Read allowed.
    assert client.get(f"/omnichannel/contacts/{contact_id}", headers=_bearer(token)).status_code == 200
    # Every write refused server-side (backend is the boundary).
    assert (
        client.post(
            f"/omnichannel/contacts/{contact_id}/messages",
            json={"body": "hi"},
            headers=_bearer(token),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/omnichannel/contacts/{contact_id}/notes",
            json={"body": "note"},
            headers=_bearer(token),
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/omnichannel/contacts/{contact_id}",
            json={"assignedUserId": "whatever"},
            headers=_bearer(token),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/omnichannel/contacts/{contact_id}/template",
            json={"templateId": "x"},
            headers=_bearer(token),
        ).status_code
        == 403
    )


def test_cap_missing_refuses_specific_write(client, session_factory):
    """A token WITH reply but WITHOUT assign can reply yet not assign."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, caps=["reply"])
    ).json()["accessToken"]
    # reply OK
    assert (
        client.post(
            f"/omnichannel/contacts/{contact_id}/messages",
            json={"body": "hi"},
            headers=_bearer(token),
        ).status_code
        == 201
    )
    # assign refused (no assign cap)
    assert (
        client.patch(
            f"/omnichannel/contacts/{contact_id}",
            json={"assignedUserId": None},
            headers=_bearer(token),
        ).status_code
        == 403
    )


def test_embed_assign_to_external_agent(client, session_factory):
    from modules.omnichannel.models import Contact

    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    r = _exchange(client, _assertion(iss=cid, workspace_id=wid, sub="u-1", name="Alice"))
    token = r.json()["accessToken"]
    agent_id = r.json()["agent"]["id"]
    res = client.patch(
        f"/omnichannel/contacts/{contact_id}",
        json={"assignedUserId": agent_id},
        headers=_bearer(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["assignedExternalAgentId"] == agent_id
    assert res.json()["assignedUserId"] is None
    # "Mine" now returns the thread for this agent.
    mine = client.get("/omnichannel/contacts?assignee=me", headers=_bearer(token))
    assert any(t["id"] == contact_id for t in mine.json()["data"])
    db = session_factory()
    c = db.query(Contact).filter(Contact.id == contact_id).first()
    assert c.assigned_external_agent_id == agent_id
    assert c.assigned_user_id is None
    db.close()


def test_embed_assign_foreign_agent_rejected(client, session_factory):
    """A token can only assign to ITS consumer's agents (connection-scoped) - a
    foreign external agent (another connection) is refused (422)."""
    from modules.omnichannel.services.external_agent_service import ExternalAgentService

    ca = _make_connection(session_factory, secret=SECRET_A)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    # A foreign agent under a DIFFERENT connection.
    db = session_factory()
    foreign = ExternalAgentService(db).upsert(
        connection_id="conn-other", tenant_id=DEFAULT_TENANT_ID, sub="x-1", name="Foreign"
    )
    foreign_id = foreign.id
    db.close()
    # A token from connection A tries to assign to the foreign agent → 422.
    a_token = _exchange(client, _assertion(iss=ca, workspace_id=wid, secret=SECRET_A)).json()["accessToken"]
    res = client.patch(
        f"/omnichannel/contacts/{contact_id}",
        json={"assignedUserId": foreign_id},
        headers=_bearer(a_token),
    )
    assert res.status_code == 422


def test_native_path_still_works(client, session_factory):
    """The native session/permission auth is unchanged on the same routes."""
    wid = _workspace_id(session_factory)
    _seed_contact(session_factory, workspace_id=wid)
    token = _native_token(client)
    res = client.get("/omnichannel/contacts", headers=_bearer(token))
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def _channel_in_workspace(session_factory, workspace_id):
    from modules.omnichannel.models import Channel

    db = session_factory()
    ch = (
        db.query(Channel)
        .filter(Channel.tenant_id == DEFAULT_TENANT_ID, Channel.workspace_id == workspace_id)
        .first()
    )
    cid = ch.id if ch else None
    db.close()
    return cid


def _other_workspace_with_channel(session_factory):
    """A SECOND workspace + a channel in it (a different tenant-scoped workspace an
    embed token for the default workspace must not be able to read)."""
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second WS", is_default=False)
    db.add(ws)
    db.flush()
    ch = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws.id,
        channel_type="WHATSAPP",
        name="Other WA",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id="pn-other",
        display_phone_number="+60 22-222 2222",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(ch)
    db.commit()
    wid, cid = ws.id, ch.id
    db.close()
    return wid, cid


# ── Finding 1: aux catalog reads reachable by the embed principal ────────────
def test_embed_reads_own_workspace_catalogs(client, session_factory):
    """The reused ConversationDrawer fetches templates / quick-replies / members
    while rendering - an embed token reads its OWN workspace's catalogs (200)."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    _seed_contact(session_factory, workspace_id=wid)  # ensures a channel in wid
    channel_id = _channel_in_workspace(session_factory, wid)
    token = _exchange(client, _assertion(iss=cid, workspace_id=wid)).json()["accessToken"]

    tmpl = client.get(f"/omnichannel/channels/{channel_id}/templates", headers=_bearer(token))
    assert tmpl.status_code == 200, tmpl.text
    assert isinstance(tmpl.json(), list)

    qr = client.get(f"/omnichannel/workspaces/{wid}/quick-replies", headers=_bearer(token))
    assert qr.status_code == 200, qr.text
    assert isinstance(qr.json(), list)

    members = client.get(f"/omnichannel/workspaces/{wid}/members", headers=_bearer(token))
    assert members.status_code == 200, members.text
    assert isinstance(members.json(), list)


def test_thread_scoped_token_reads_workspace_catalogs(client, session_factory):
    """A thread:<contactId> token may still read its workspace's catalogs (it
    needs templates to send / members to see assignees) - scope confines it to
    its OWN workspace, not to zero catalog access."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    contact_id = _seed_contact(session_factory, workspace_id=wid)
    token = _exchange(
        client, _assertion(iss=cid, workspace_id=wid, scope=f"thread:{contact_id}")
    ).json()["accessToken"]
    assert client.get(f"/omnichannel/workspaces/{wid}/quick-replies", headers=_bearer(token)).status_code == 200
    assert client.get(f"/omnichannel/workspaces/{wid}/members", headers=_bearer(token)).status_code == 200


def test_embed_reads_other_workspace_refused(client, session_factory):
    """A token for workspace A is refused workspace B's quick-replies / members
    AND another workspace's channel templates (403) - backend is the boundary."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    other_wid, other_channel = _other_workspace_with_channel(session_factory)
    token = _exchange(client, _assertion(iss=cid, workspace_id=wid)).json()["accessToken"]

    assert (
        client.get(f"/omnichannel/workspaces/{other_wid}/quick-replies", headers=_bearer(token)).status_code
        == 403
    )
    assert (
        client.get(f"/omnichannel/workspaces/{other_wid}/members", headers=_bearer(token)).status_code == 403
    )
    assert (
        client.get(f"/omnichannel/channels/{other_channel}/templates", headers=_bearer(token)).status_code
        == 403
    )


def test_native_reads_aux_catalogs_still_work(client, session_factory):
    """The native session path is unchanged on the relocated read endpoints."""
    wid = _workspace_id(session_factory)
    _seed_contact(session_factory, workspace_id=wid)
    channel_id = _channel_in_workspace(session_factory, wid)
    token = _native_token(client)
    assert client.get(f"/omnichannel/channels/{channel_id}/templates", headers=_bearer(token)).status_code == 200
    assert client.get(f"/omnichannel/workspaces/{wid}/quick-replies", headers=_bearer(token)).status_code == 200
    assert client.get(f"/omnichannel/workspaces/{wid}/members", headers=_bearer(token)).status_code == 200


def test_embed_token_rejected_on_staff_endpoint(client, session_factory):
    """Defense-in-depth: an embed access token can't authenticate a staff route."""
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    token = _exchange(client, _assertion(iss=cid, workspace_id=wid)).json()["accessToken"]
    # /auth/me is a staff endpoint gated by get_current_user.
    res = client.get("/auth/me", headers=_bearer(token))
    assert res.status_code == 401


# ── Slice 3: WS accepts the embed access token (AC-11H-09) ───────────────────
def test_ws_accepts_embed_token_and_relays(client, session_factory):
    import json

    import fakeredis
    import fakeredis.aioredis
    from modules.omnichannel.routers import ws as ws_module
    from modules.omnichannel.services import realtime

    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(
        fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    )
    ws_module.set_session_factory(session_factory)
    try:
        cid = _make_connection(session_factory)
        wid = _workspace_id(session_factory)
        token = _exchange(client, _assertion(iss=cid, workspace_id=wid)).json()["accessToken"]
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={wid}&token={token}"
        ) as sock:
            realtime.publish(wid, {"type": "message.status", "messageId": "m1"})
            event = json.loads(sock.receive_text())
            assert event == {"type": "message.status", "messageId": "m1"}
    finally:
        realtime.set_client(None)
        ws_module.set_async_redis(None)
        ws_module.set_session_factory(ws_module.SessionLocal)


def test_ws_rejects_embed_token_for_wrong_workspace(client, session_factory):
    import fakeredis
    import fakeredis.aioredis
    import pytest
    from starlette.websockets import WebSocketDisconnect
    from modules.omnichannel.routers import ws as ws_module
    from modules.omnichannel.services import realtime

    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(
        fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    )
    ws_module.set_session_factory(session_factory)
    try:
        cid = _make_connection(session_factory)
        wid = _workspace_id(session_factory)
        token = _exchange(client, _assertion(iss=cid, workspace_id=wid)).json()["accessToken"]
        # A token minted for `wid` cannot open a socket on a different workspace.
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                f"/omnichannel/ws?workspaceId=other-ws&token={token}"
            ):
                pass
        assert exc.value.code == 4403
    finally:
        realtime.set_client(None)
        ws_module.set_async_redis(None)
        ws_module.set_session_factory(ws_module.SessionLocal)


def test_ws_thread_scope_filters_other_contacts(client, session_factory):
    """AC-11H-10 over WS: a thread:<contactId> token receives ONLY its contact's
    frames - the whole-workspace fan-out is filtered server-side, never left to
    the widget. A frame for another contact is dropped."""
    import json

    import fakeredis
    import fakeredis.aioredis
    from modules.omnichannel.routers import ws as ws_module
    from modules.omnichannel.services import realtime

    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(
        fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    )
    ws_module.set_session_factory(session_factory)
    try:
        cid = _make_connection(session_factory)
        wid = _workspace_id(session_factory)
        token = _exchange(
            client,
            _assertion(iss=cid, workspace_id=wid, scope="thread:c-scoped"),
        ).json()["accessToken"]
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={wid}&token={token}"
        ) as sock:
            # Frame for another contact - must be dropped by the server.
            realtime.publish(
                wid, {"type": "message.status", "messageId": "m-other", "contactId": "c-other"}
            )
            # Frame for the scoped contact - must arrive.
            realtime.publish(
                wid, {"type": "message.status", "messageId": "m-mine", "contactId": "c-scoped"}
            )
            event = json.loads(sock.receive_text())
            assert event["messageId"] == "m-mine"
            assert event["contactId"] == "c-scoped"
    finally:
        realtime.set_client(None)
        ws_module.set_async_redis(None)
        ws_module.set_session_factory(ws_module.SessionLocal)


# ── Slice 4: frame-policy (AC-11H-15 frame-ancestors source) ─────────────────
def test_frame_policy_returns_allowed_origins(client, session_factory):
    cid = _make_connection(session_factory)
    res = client.get(f"/embed/frame-policy?c={cid}")
    assert res.status_code == 200
    assert ORIGIN in res.json()["allowedOrigins"]


def test_frame_policy_unknown_connection_is_empty(client):
    """Unknown / absent connection → empty (uniform, no enumeration) → the
    middleware emits frame-ancestors 'none'."""
    assert client.get("/embed/frame-policy?c=does-not-exist").json()["allowedOrigins"] == []
    assert client.get("/embed/frame-policy").json()["allowedOrigins"] == []


# ── Slice 2: throttle ────────────────────────────────────────────────────────
def test_embed_session_throttled(client, session_factory):
    cid = _make_connection(session_factory)
    wid = _workspace_id(session_factory)
    original = settings.throttle_embed_max_fails
    settings.throttle_embed_max_fails = 3
    try:
        # Bad-signature attempts pump the IP bucket.
        for _ in range(3):
            _exchange(client, _assertion(iss=cid, workspace_id=wid, secret="wrong-secret-0000000000"))
        res = _exchange(client, _assertion(iss=cid, workspace_id=wid))
        assert res.status_code == 429
        assert "Retry-After" in res.headers
    finally:
        settings.throttle_embed_max_fails = original
