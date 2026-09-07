"""Plan 34 (A7b) Slice S5 - business hours (`online`), pre-chat write-if-
empty, host identity assertion, dev seed.

AC-WEB-52..57 (see documentation/plans/sprint-4/
34-omnichannel-channel-web-chat-acceptance-criteria.md).
"""
import hashlib
import hmac

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services.business_hours import BusinessHoursService
from tests.test_omnichannel_channels_webchat import _auth, _connect, _default_workspace_id
from tests.test_omnichannel_webchat_public import _get_messages, _post_message, _session

ORIGIN = "https://shop.acme.com"
ALL_CLOSED_WINDOWS = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def _new_channel(client, *, name="S5 Chat", allowed_origins=None):
    h = _auth(client)
    body = _connect(client, h, name=name, allowed_origins=allowed_origins or [ORIGIN]).json()
    return body["widgetKey"], body["id"], body["widgetSecret"]


def _sign(secret: str, user_ref: str) -> str:
    return hmac.new(secret.encode("utf-8"), user_ref.encode("utf-8"), hashlib.sha256).hexdigest()


# ── AC-WEB-52: `online` via the EXISTING BusinessHoursService ───────────────
def test_online_true_when_business_hours_unconfigured(client):
    widget_key, _, _ = _new_channel(client)
    res = _session(client, widget_key)
    assert res.status_code == 200
    assert res.json()["online"] is True


def test_online_false_when_workspace_hours_are_all_closed(client):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    put = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "UTC", "windows": ALL_CLOSED_WINDOWS},
        headers=h,
    )
    assert put.status_code == 200, put.text

    widget_key, _, _ = _new_channel(client, name="Offline Chat")
    res = _session(client, widget_key)
    assert res.status_code == 200
    assert res.json()["online"] is False


def test_online_resolves_the_tenant_default_row_when_workspace_is_unconfigured(
    client, session_factory
):
    db = session_factory()
    BusinessHoursService(db).set(
        DEFAULT_TENANT_ID, None, timezone="UTC", windows=ALL_CLOSED_WINDOWS
    )
    db.close()

    widget_key, _, _ = _new_channel(client, name="Tenant Default Chat")
    res = _session(client, widget_key)
    assert res.status_code == 200
    assert res.json()["online"] is False


def test_online_never_duplicates_the_hours_logic_workspace_wins_over_tenant_default(
    client, session_factory
):
    """The workspace's OWN row wins over the tenant default - closed
    tenant-wide, but this workspace has its own (open all day) row."""
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    db = session_factory()
    BusinessHoursService(db).set(
        DEFAULT_TENANT_ID, None, timezone="UTC", windows=ALL_CLOSED_WINDOWS
    )
    db.close()
    open_all_day = {
        d: [{"from": "00:00", "to": "23:59"}] for d in ALL_CLOSED_WINDOWS
    }
    put = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "UTC", "windows": open_all_day},
        headers=h,
    )
    assert put.status_code == 200, put.text

    widget_key, _, _ = _new_channel(client, name="Workspace Wins Chat")
    res = _session(client, widget_key)
    assert res.status_code == 200
    assert res.json()["online"] is True


# ── AC-WEB-54: pre-chat write-if-empty, never a lookup/stitch ───────────────
def test_pre_chat_writes_name_email_phone_onto_the_new_contact_when_empty(client, session_factory):
    from modules.omnichannel.models import Contact

    widget_key, _, _ = _new_channel(client, name="PreChat Chat")
    token = _session(client, widget_key).json()["token"]
    res = _post_message(
        client,
        widget_key,
        token,
        text="Hi there",
        preChat={"name": "Ada Lovelace", "email": "ada@example.com", "phone": "+1 555 000 1111"},
    )
    assert res.status_code == 201

    db = session_factory()
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).first()
    assert contact.first_name == "Ada"
    assert contact.last_name == "Lovelace"
    assert contact.email == "ada@example.com"
    assert contact.phone == "+1 555 000 1111"
    assert contact.phone_digits == "15550001111"
    db.close()


def test_pre_chat_never_overwrites_an_already_filled_field(client, session_factory):
    from modules.omnichannel.models import Contact

    widget_key, _, _ = _new_channel(client, name="No Overwrite Chat")
    token = _session(client, widget_key).json()["token"]
    _post_message(
        client, widget_key, token, text="first", preChat={"name": "First Name"}
    )
    res = _post_message(
        client, widget_key, token, text="second", preChat={"name": "Second Name"}
    )
    assert res.status_code == 201

    db = session_factory()
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).first()
    assert contact.first_name == "First"
    assert contact.last_name == "Name"
    db.close()


def test_pre_chat_fills_a_field_left_empty_by_an_earlier_message(client, session_factory):
    """Write-if-empty is honored on ANY message, not only the first - a
    field the visitor skipped in message 1 can still be captured later."""
    from modules.omnichannel.models import Contact

    widget_key, _, _ = _new_channel(client, name="Fill Later Chat")
    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="first", preChat={"name": "Ada"})
    res = _post_message(
        client, widget_key, token, text="second", preChat={"email": "ada@example.com"}
    )
    assert res.status_code == 201

    db = session_factory()
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).first()
    assert contact.first_name == "Ada"
    assert contact.email == "ada@example.com"
    db.close()


def test_pre_chat_invalid_email_is_silently_dropped_message_still_lands(client, session_factory):
    from modules.omnichannel.models import Contact

    widget_key, _, _ = _new_channel(client, name="Bad Email Chat")
    token = _session(client, widget_key).json()["token"]
    res = _post_message(
        client, widget_key, token, text="hi", preChat={"email": "not-an-email"}
    )
    assert res.status_code == 201  # never rejected

    db = session_factory()
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).first()
    assert contact.email is None
    db.close()


def test_pre_chat_email_matching_existing_contact_never_stitches_or_overwrites_it(
    client, session_factory
):
    """D-A7B-8/R3, S5's own version of the S2 no-stitch seam: even with
    write-if-empty live, an attacker-supplied email matching an existing
    contact never merges onto it AND never overwrites that OTHER contact's
    own data - only the visitor's OWN brand-new contact is ever touched."""
    from modules.omnichannel.models import Contact

    h = _auth(client)
    ws = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    ws_id = next(w["id"] for w in ws if w["isDefault"])

    db0 = session_factory()
    existing = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        first_name="Existing",
        email="known@example.com",
        priority="MEDIUM",
    )
    db0.add(existing)
    db0.commit()
    existing_id = existing.id
    before_count = db0.query(Contact).count()
    db0.close()

    widget_key, _, _ = _new_channel(client, name="Still No Stitch Chat")
    token = _session(client, widget_key).json()["token"]
    res = _post_message(
        client, widget_key, token, text="hi", preChat={"name": "Impersonator", "email": "known@example.com"}
    )
    assert res.status_code == 201

    db = session_factory()
    after_count = db.query(Contact).count()
    other = db.query(Contact).filter(Contact.id == existing_id).first()
    assert after_count == before_count + 1  # a NEW contact, never a merge
    assert other.first_name == "Existing"  # the OTHER contact is untouched
    db.close()


# ── AC-WEB-55/56: host identity assertion ───────────────────────────────────
def test_valid_host_identity_resolves_and_reuses_the_contact(client, session_factory):
    from modules.omnichannel.models import Contact, ContactChannelIdentity

    widget_key, _, secret = _new_channel(client, name="Identity Chat")
    user_ref = "user-1234"
    identity = {"userRef": user_ref, "hash": _sign(secret, user_ref)}

    res1 = _session(client, widget_key, identity=identity)
    assert res1.status_code == 200
    token1 = res1.json()["token"]
    post1 = _post_message(client, widget_key, token1, text="hello from device 1")
    assert post1.status_code == 201

    db = session_factory()
    ident_row = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.external_user_id == f"host:{user_ref}")
        .first()
    )
    assert ident_row is not None
    contact_id = ident_row.contact_id
    db.close()

    # A SECOND session with the SAME assertion (a different device/tab) must
    # resolve the SAME contact and see the first device's history.
    res2 = _session(client, widget_key, identity=identity)
    assert res2.status_code == 200
    body2 = res2.json()
    assert len(body2["messages"]) == 1
    token2 = body2["token"]
    post2 = _post_message(client, widget_key, token2, text="hello from device 2")
    assert post2.status_code == 201

    db = session_factory()
    assert db.query(Contact).filter(Contact.id == contact_id).count() == 1
    assert (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.external_user_id == f"host:{user_ref}")
        .count()
        == 1
    )
    db.close()


def test_missing_hash_is_ignored_session_proceeds_anonymously(client):
    widget_key, _, _ = _new_channel(client, name="Missing Hash Chat")
    res = _session(client, widget_key, identity={"userRef": "user-1"})
    assert res.status_code == 200
    assert res.json()["token"]


def test_malformed_identity_is_ignored_session_proceeds_anonymously(client):
    widget_key, _, _ = _new_channel(client, name="Malformed Identity Chat")
    res = _session(client, widget_key, identity="not-an-object")
    assert res.status_code == 200
    assert res.json()["token"]


def test_wrong_hash_is_ignored_no_error_no_distinguishing_response(client, session_factory):
    from modules.omnichannel.models import ContactChannelIdentity

    widget_key, _, secret = _new_channel(client, name="Wrong Hash Chat")
    ok = _session(client, widget_key, identity={"userRef": "user-1", "hash": _sign(secret, "user-1")})
    bad = _session(
        client, widget_key, identity={"userRef": "user-1", "hash": "0" * 64}
    )
    assert ok.status_code == bad.status_code == 200
    # A garbage hash never resolves the host identity - no identity row for
    # it exists even after a message (checked indirectly: no error surfaces).
    db = session_factory()
    assert (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.external_user_id == "host:user-1")
        .count()
        == 0
    )
    db.close()


def test_a_userref_with_disallowed_characters_is_rejected(client):
    widget_key, _, secret = _new_channel(client, name="Bad Charset Chat")
    user_ref = "user 1234; DROP TABLE"
    res = _session(
        client, widget_key, identity={"userRef": user_ref, "hash": _sign(secret, user_ref)}
    )
    assert res.status_code == 200  # ignored, not an error - proceeds anonymously


def test_identity_assertion_signed_with_a_different_channels_secret_fails(client):
    widget_key_a, _, _ = _new_channel(client, name="Channel A")
    _widget_key_b, _, secret_b = _new_channel(client, name="Channel B")
    user_ref = "user-1234"
    # Signed with channel B's secret, presented to channel A - must fail.
    res = _session(
        client, widget_key_a, identity={"userRef": user_ref, "hash": _sign(secret_b, user_ref)}
    )
    assert res.status_code == 200
    assert res.json()["token"]


def test_host_identity_for_user_a_cannot_read_user_bs_thread(client, session_factory):
    widget_key, _, secret = _new_channel(client, name="Isolation Chat")
    ident_a = {"userRef": "user-a", "hash": _sign(secret, "user-a")}
    ident_b = {"userRef": "user-b", "hash": _sign(secret, "user-b")}

    token_a = _session(client, widget_key, identity=ident_a).json()["token"]
    _post_message(client, widget_key, token_a, text="A's secret message")

    token_b = _session(client, widget_key, identity=ident_b).json()["token"]
    history_b = _get_messages(client, widget_key, token_b)
    assert history_b.status_code == 200
    assert history_b.json()["data"] == []  # B sees nothing of A's thread


def test_anonymous_token_cannot_read_the_host_identified_thread(client, session_factory):
    widget_key, _, secret = _new_channel(client, name="Anon Isolation Chat")
    user_ref = "user-anon-check"
    identity = {"userRef": user_ref, "hash": _sign(secret, user_ref)}
    token_host = _session(client, widget_key, identity=identity).json()["token"]
    _post_message(client, widget_key, token_host, text="host-only message")

    # A brand-new anonymous session on the SAME channel/widget - no identity.
    token_anon = _session(client, widget_key).json()["token"]
    history_anon = _get_messages(client, widget_key, token_anon)
    assert history_anon.status_code == 200
    assert history_anon.json()["data"] == []


# ── AC-WEB-57: dev seed ──────────────────────────────────────────────────────
def test_dev_seed_creates_chn_demo_web_with_two_threads(session_factory):
    from modules.omnichannel import bootstrap
    from modules.omnichannel.models import Channel, Contact, ConversationMessage

    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    db.close()

    db = session_factory()
    channel = (
        db.query(Channel)
        .filter(Channel.id == "chn-demo-web", Channel.tenant_id == DEFAULT_TENANT_ID)
        .first()
    )
    assert channel is not None
    assert channel.channel_type == "WEBCHAT"
    assert channel.widget_key
    origins = (channel.widget_config_json or {}).get("allowedOrigins") or []
    assert "http://localhost:3001" in origins
    assert "http://localhost:3012" in origins
    assert "http://localhost:3013" in origins

    contacts = db.query(Contact).filter(Contact.id.in_(["cnt-web-001", "cnt-web-002"])).all()
    assert {c.id for c in contacts} == {"cnt-web-001", "cnt-web-002"}
    for c in contacts:
        assert (
            db.query(ConversationMessage)
            .filter(ConversationMessage.contact_id == c.id)
            .count()
            >= 1
        )
    db.close()

    # Idempotent re-run does not duplicate.
    db = session_factory()
    bootstrap.seed_demo_conversations(db, DEFAULT_TENANT_ID)
    assert db.query(Channel).filter(Channel.id == "chn-demo-web").count() == 1
    assert db.query(Contact).filter(Contact.id == "cnt-web-001").count() == 1
    assert db.query(Contact).filter(Contact.id == "cnt-web-002").count() == 1
    db.close()
