"""Omnichannel Contacts module - plan 26 S1 (list, filter/sort, segments,
phone_digits, permissions). Covers AC-CTM-14..23, 43, plus this slice's share
of AC-CTM-46 (list/segment/permission/tenant-isolation pytest matrix).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _base(ws_id: str) -> str:
    return f"/omnichannel/workspaces/{ws_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_channel(session_factory, ws_id, *, channel_type="WHATSAPP", name="Test WhatsApp"):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    channel = db.query(Channel).filter(Channel.channel_type == channel_type).first()
    if channel is None:
        channel = Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=ws_id,
            channel_type=channel_type,
            name=name,
            credentials_json=encrypt_credentials({"dev": True}),
            phone_number_id=f"pn-{channel_type.lower()}",
            display_phone_number="+60 11-111 1111",
            is_active=True,
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
        db.add(channel)
        db.commit()
    cid = channel.id
    db.close()
    return cid


def _seed_contact(
    session_factory,
    ws_id,
    *,
    first="John",
    last="Doe",
    email=None,
    phone=None,
    language=None,
    country_code=None,
    priority="MEDIUM",
    assigned_email=None,
    unassigned=False,
    custom_fields=None,
    tag_names=None,
    lifecycle_key=None,
    last_message_at=None,
    created_at=None,
    channel_id=None,
):
    from modules.omnichannel.models import Contact, ContactChannelIdentity, ContactTag, ContactTagLink
    from modules.omnichannel.phone import digits_only
    from modules.omnichannel.services import lifecycle_service

    db = session_factory()
    assigned_id = None
    if assigned_email and not unassigned:
        assigned_id = db.query(User).filter(User.email == assigned_email).first().id

    lifecycle_status_id = None
    if lifecycle_key:
        stage = next(
            s
            for s in lifecycle_service.stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)
            if s.key == lifecycle_key
        )
        lifecycle_status_id = stage.id

    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        first_name=first,
        last_name=last,
        email=email,
        phone=phone,
        phone_digits=digits_only(phone) if phone else None,
        language=language,
        country_code=country_code,
        priority=priority,
        assigned_user_id=assigned_id,
        custom_fields_json=custom_fields,
        lifecycle_status_id=lifecycle_status_id,
        last_message_at=last_message_at,
        created_at=created_at or _now(),
    )
    db.add(contact)
    db.flush()

    for name in tag_names or []:
        tag = (
            db.query(ContactTag)
            .filter(ContactTag.workspace_id == ws_id, ContactTag.name == name)
            .first()
        )
        if tag is None:
            tag = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws_id, name=name)
            db.add(tag)
            db.flush()
        db.add(ContactTagLink(tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, tag_id=tag.id))

    if channel_id:
        db.add(
            ContactChannelIdentity(
                tenant_id=DEFAULT_TENANT_ID,
                contact_id=contact.id,
                channel_id=channel_id,
                external_user_id=contact.phone_digits or contact.id,
            )
        )

    db.commit()
    cid = contact.id
    db.close()
    return cid


def _tag_id(session_factory, ws_id, name):
    from modules.omnichannel.models import ContactTag

    db = session_factory()
    tag = db.query(ContactTag).filter(ContactTag.workspace_id == ws_id, ContactTag.name == name).first()
    tid = tag.id
    db.close()
    return tid


def _lifecycle_ids(session_factory, ws_id):
    from modules.omnichannel.services import lifecycle_service

    db = session_factory()
    out = {s.key: s.id for s in lifecycle_service.stages_for_workspace(db, DEFAULT_TENANT_ID, ws_id)}
    db.close()
    return out


# ── AC-CTM-14: list shape, default sort, pagination cap ──────────────────────
def test_list_default_shape_and_sort(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    older = _seed_contact(
        session_factory, ws, first="Older", last_message_at=_now() - timedelta(hours=2)
    )
    newer = _seed_contact(
        session_factory, ws, first="Newer", last_message_at=_now() - timedelta(minutes=5)
    )
    no_message = _seed_contact(session_factory, ws, first="NoMessage")

    res = client.get(f"{_base(ws)}/contacts", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 0
    assert body["total"] == 3
    ids = [c["id"] for c in body["data"]]
    # newest lastMessageAt first, then null-lastMessageAt rows last.
    assert ids == [newer, older, no_message]
    item = body["data"][0]
    assert set(["id", "phone", "email", "lifecycle", "tags", "channels", "assignedUserName"]) <= set(item.keys())
    assert item["channels"] == []


def test_list_page_size_cap_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"pageSize": 500})
    assert res.status_code == 422


# ── AC-CTM-15: search (name / phone digits / email, never message bodies) ────
def test_search_matches_name_phone_digits_email_never_message_body(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    target = _seed_contact(
        session_factory, ws, first="Zara", last="Wolfe", email="zara@example.com", phone="+60 12-345 6789"
    )
    other = _seed_contact(session_factory, ws, first="Other", last="Person", email="other@example.com")

    by_name = client.get(f"{_base(ws)}/contacts", headers=h, params={"search": "zara"}).json()
    assert [c["id"] for c in by_name["data"]] == [target]

    by_full_name = client.get(f"{_base(ws)}/contacts", headers=h, params={"search": "zara wolfe"}).json()
    assert [c["id"] for c in by_full_name["data"]] == [target]

    by_email = client.get(f"{_base(ws)}/contacts", headers=h, params={"search": "ZARA@EXAMPLE"}).json()
    assert [c["id"] for c in by_email["data"]] == [target]

    # Phone search is digits-insensitive to formatting - "12345" spans a
    # formatting boundary ("12-345") in the stored phone.
    by_phone = client.get(f"{_base(ws)}/contacts", headers=h, params={"search": "123456789"}).json()
    assert [c["id"] for c in by_phone["data"]] == [target]

    # Never matches a message body (that stays on the Inbox thread list).
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    db.add(
        ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID, contact_id=other, sender_type="CONTACT",
            message_type="TEXT", body="unique-message-body-zara-wolfe-marker",
        )
    )
    db.commit()
    db.close()
    by_body = client.get(
        f"{_base(ws)}/contacts", headers=h, params={"search": "unique-message-body-zara-wolfe-marker"}
    ).json()
    assert by_body["data"] == []


# ── AC-CTM-16: filter over the whitelisted column map + 422s ─────────────────
def _cond(field, op, value):
    return {"kind": "condition", "field": field, "operator": op, "value": value}


def _group(rules, combinator="and"):
    return {"kind": "group", "combinator": combinator, "rules": rules}


def test_filter_system_fields(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    target = _seed_contact(
        session_factory, ws, first="Amelia", last="Storm", language="en", country_code="MY", priority="HIGH"
    )
    _seed_contact(session_factory, ws, first="Someone", last="Else", language="fr", country_code="SG", priority="LOW")

    tree = _group([
        _cond("firstName", "eq", "Amelia"),
        _cond("language", "eq", "en"),
        _cond("countryCode", "eq", "MY"),
        _cond("priority", "eq", "HIGH"),
    ])
    import json as _json

    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"filter": _json.dumps(tree)})
    assert res.status_code == 200
    assert [c["id"] for c in res.json()["data"]] == [target]


def test_generic_text_clause_neq_includes_null_rows(client, session_factory):
    """Nit 19 (review round 1): SQL three-valued logic means a bare
    `expr != val` excludes a NULL row (`NULL != val` is NULL, not TRUE) - a
    contact with no value AT ALL for the column trivially IS "not equal to
    X" and must match `neq` too. Unit-tested directly against
    `_generic_text_clause` (the module's own `"name"` field always passes it
    a `coalesce(...)`-wrapped, never-NULL expression, so an HTTP-level
    round-trip through `name` can never exercise the NULL branch)."""
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services.contact_filters import _generic_text_clause
    from app.schemas.filters import FilterCondition

    h = _auth(client)
    ws = _workspace_id(client, h)
    other = _seed_contact(session_factory, ws, first="Someone", last=None)
    no_value = _seed_contact(session_factory, ws, first=None, last=None)
    _seed_contact(session_factory, ws, first="Amelia", last=None)

    cond = FilterCondition(kind="condition", field="firstName", operator="neq", value="Amelia")
    clause = _generic_text_clause(Contact.first_name, cond, name="firstName")

    db = session_factory()
    ids = {
        r[0]
        for r in db.query(Contact.id).filter(Contact.id.in_([other, no_value]), clause).all()
    }
    db.close()
    assert ids == {other, no_value}


def test_filter_unknown_field_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_cond("notAField", "eq", "x"))},
    )
    assert res.status_code == 422


def test_filter_depth_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    import json as _json

    tree = _cond("firstName", "eq", "x")
    for _ in range(8):
        tree = _group([tree])
    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"filter": _json.dumps(tree)})
    assert res.status_code == 422


def test_filter_tags_matches_any(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    tagged = _seed_contact(session_factory, ws, first="Tagged", tag_names=["VIP"])
    _seed_contact(session_factory, ws, first="Untagged")
    tag_id = _tag_id(session_factory, ws, "VIP")

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("tags", "in", [tag_id])]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [tagged]


def test_filter_lifecycle(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    hot = _seed_contact(session_factory, ws, first="Hot", lifecycle_key="hot_lead")
    _seed_contact(session_factory, ws, first="New", lifecycle_key="new_lead")

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("lifecycle", "eq", "hot_lead")]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [hot]


def test_filter_assignee_including_unassigned(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    mine = _seed_contact(session_factory, ws, first="Mine", assigned_email=ACTIVE_EMAIL)
    unassigned = _seed_contact(session_factory, ws, first="Unassigned")

    import json as _json

    db_user_id = None
    from app.database import SessionLocal  # noqa: F401 - not used; kept for parity with other tests

    admin = client.get("/auth/me", headers=h).json()
    admin_id = admin["id"]

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("assignee", "in", [admin_id])]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [mine]

    res2 = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("assignee", "in", ["unassigned"])]))},
    )
    assert [c["id"] for c in res2.json()["data"]] == [unassigned]


def test_filter_channel_type(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    wa_channel = _ensure_channel(session_factory, ws, channel_type="WHATSAPP")
    on_wa = _seed_contact(session_factory, ws, first="OnWa", channel_id=wa_channel)
    _seed_contact(session_factory, ws, first="NoChannel")

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("channelType", "in", ["WHATSAPP"])]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [on_wa]


# ── AC-CTM-17: customFields.<key> resolves only for a REGISTERED key ─────────
def test_filter_custom_field_registered_key(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "company", "label": "Company", "type": "text",
    })
    matching = _seed_contact(session_factory, ws, first="Acme", custom_fields={"company": "Acme Inc"})
    _seed_contact(session_factory, ws, first="Other", custom_fields={"company": "Other Co"})

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("customFields.company", "contains", "Acme")]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [matching]


def test_filter_custom_field_boolean_portable(client, session_factory):
    """Dialect-portable JSON accessor - passes identically on the SQLite test
    engine (this suite) and on Postgres (`.as_boolean()`)."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "isVip", "label": "VIP", "type": "checkbox",
    })
    vip = _seed_contact(session_factory, ws, first="VipOne", custom_fields={"isVip": True})
    _seed_contact(session_factory, ws, first="NotVip", custom_fields={"isVip": False})

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_group([_cond("customFields.isVip", "is_true", None)]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [vip]


def test_filter_custom_field_unregistered_key_422(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_cond("customFields.ghost", "eq", "x"))},
    )
    assert res.status_code == 422


def test_filter_custom_field_deleted_key_422(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    created = client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "temp", "label": "Temp", "type": "text",
    }).json()
    client.delete(f"{_base(ws)}/contact-fields/{created['id']}", headers=h)

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"filter": _json.dumps(_cond("customFields.temp", "eq", "x"))},
    )
    assert res.status_code == 422


# ── AC-CTM-18: sort whitelist ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "sort_by", ["name", "phone", "email", "lifecycle", "assignee", "lastMessageAt", "createdAt"]
)
def test_sort_every_whitelisted_key_accepted(client, session_factory, sort_by):
    h = _auth(client)
    ws = _workspace_id(client, h)
    _seed_contact(session_factory, ws, first="A", phone="+1111", email="a@example.com", lifecycle_key="new_lead")
    _seed_contact(session_factory, ws, first="B", phone="+2222", email="b@example.com", lifecycle_key="hot_lead")

    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"sortBy": sort_by, "sortDir": "asc"})
    assert res.status_code == 200
    assert len(res.json()["data"]) == 2


def test_sort_name_and_phone_order(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    z = _seed_contact(session_factory, ws, first="Zeta", phone="+2000000000")
    a = _seed_contact(session_factory, ws, first="Alpha", phone="+1000000000")

    by_name = client.get(f"{_base(ws)}/contacts", headers=h, params={"sortBy": "name", "sortDir": "asc"}).json()
    assert [c["id"] for c in by_name["data"]] == [a, z]

    by_phone = client.get(f"{_base(ws)}/contacts", headers=h, params={"sortBy": "phone", "sortDir": "asc"}).json()
    assert [c["id"] for c in by_phone["data"]] == [a, z]


def test_sort_unknown_key_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"sortBy": "notASortKey"})
    assert res.status_code == 422


def test_sort_dir_invalid_422(client):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.get(f"{_base(ws)}/contacts", headers=h, params={"sortBy": "name", "sortDir": "sideways"})
    assert res.status_code == 422


# ── AC-CTM-19: channels[] batched, tenant-scoped, never fabricated ───────────
def test_channels_resolved_from_identities_never_fabricated(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    wa = _ensure_channel(session_factory, ws, channel_type="WHATSAPP")
    with_channel = _seed_contact(session_factory, ws, first="Chan", channel_id=wa)
    no_channel = _seed_contact(session_factory, ws, first="NoChan")

    data = {c["id"]: c for c in client.get(f"{_base(ws)}/contacts", headers=h).json()["data"]}
    assert data[with_channel]["channels"] == [
        {"channelId": wa, "channelType": "WHATSAPP", "name": "Test WhatsApp"}
    ]
    assert data[no_channel]["channels"] == []


# ── AC-CTM-20/21: segments CRUD + apply + uniqueness + cap ──────────────────
def test_segment_crud_and_uniqueness(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    tree = _group([_cond("priority", "eq", "HIGH")])

    created = client.post(f"{_base(ws)}/contact-segments", headers=h, json={
        "name": "Hot leads", "description": "high priority", "filter": tree,
    })
    assert created.status_code == 201
    sid = created.json()["id"]
    assert created.json()["filter"]["rules"][0]["field"] == "priority"

    dup = client.post(f"{_base(ws)}/contact-segments", headers=h, json={
        "name": "hot leads", "filter": tree,
    })
    assert dup.status_code == 422
    assert "name" in dup.json()["detail"]["fieldErrors"]

    listed = client.get(f"{_base(ws)}/contact-segments", headers=h).json()
    assert any(s["id"] == sid for s in listed)

    renamed = client.patch(f"{_base(ws)}/contact-segments/{sid}", headers=h, json={"name": "VIP leads"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "VIP leads"

    deleted = client.delete(f"{_base(ws)}/contact-segments/{sid}", headers=h)
    assert deleted.status_code == 204
    assert client.get(f"{_base(ws)}/contact-segments", headers=h).json() == []


def test_segment_save_time_validation_rejects_unknown_field(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    res = client.post(f"{_base(ws)}/contact-segments", headers=h, json={
        "name": "Bad", "filter": _group([_cond("notAField", "eq", "x")]),
    })
    assert res.status_code == 422
    assert "filter" in res.json()["detail"]["fieldErrors"]
    assert client.get(f"{_base(ws)}/contact-segments", headers=h).json() == []


def test_segment_apply_ands_with_ad_hoc_filter(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    both = _seed_contact(session_factory, ws, first="Both", priority="HIGH", language="en")
    _seed_contact(session_factory, ws, first="OnlyHigh", priority="HIGH", language="fr")
    _seed_contact(session_factory, ws, first="OnlyEn", priority="LOW", language="en")

    seg = client.post(f"{_base(ws)}/contact-segments", headers=h, json={
        "name": "High priority", "filter": _group([_cond("priority", "eq", "HIGH")]),
    }).json()

    import json as _json

    res = client.get(
        f"{_base(ws)}/contacts", headers=h,
        params={"segment": seg["id"], "filter": _json.dumps(_group([_cond("language", "eq", "en")]))},
    )
    assert [c["id"] for c in res.json()["data"]] == [both]


def test_segment_cap_100_per_workspace(client, session_factory):
    from modules.omnichannel.models import ContactSegment

    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    for i in range(100):
        db.add(ContactSegment(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name=f"seg{i}", filter_json=None))
    db.commit()
    db.close()

    res = client.post(f"{_base(ws)}/contact-segments", headers=h, json={"name": "one more"})
    assert res.status_code == 422


# ── AC-CTM-22: permission gates + tenant isolation (uniform 404) ────────────
def _no_perm_auth(client, session_factory, email="ctm-noperm@example.com"):
    db = session_factory()
    db.add(User(
        tenant_id=DEFAULT_TENANT_ID, email=email, name="No Perm",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    ))
    db.commit()
    db.close()
    return _auth(client, email=email, password="Password123!")


def _read_only_auth(client, session_factory, email="ctm-readonly@example.com"):
    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Contacts Read Only")
    role.permissions = PermissionRepository(db).get_by_keys(["contacts.read"])
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, name="Read Only",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()
    return _auth(client, email=email, password="Password123!")


def test_permission_gates_403(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    h_none = _no_perm_auth(client, session_factory)
    assert client.get(f"{_base(ws)}/contacts", headers=h_none).status_code == 403
    assert client.get(f"{_base(ws)}/contact-segments", headers=h_none).status_code == 403
    assert client.post(f"{_base(ws)}/contact-segments", headers=h_none, json={"name": "x"}).status_code == 403

    h_read = _read_only_auth(client, session_factory)
    assert client.get(f"{_base(ws)}/contacts", headers=h_read).status_code == 200
    assert client.get(f"{_base(ws)}/contact-segments", headers=h_read).status_code == 200
    assert client.post(f"{_base(ws)}/contact-segments", headers=h_read, json={"name": "x"}).status_code == 403


def test_contact_detail_read_accepts_contacts_read_alone(client, session_factory):
    """AC-CTM-22 (phase-2 fix): the Contacts module's detail page reuses the
    A1 inbox routes `GET /omnichannel/contacts/{id}` (`contact-service.real.ts
    get`) and `.../messages` (the embedded `<ConversationDrawer>`) - a role
    holding ONLY `contacts.read` (no `conversations.read`) must still be able
    to open a contact's own detail page, even though it stays refused on the
    shared Inbox LIST (`GET /omnichannel/contacts` bare, `conversations.read`
    only - `contacts.read` must not silently grant Inbox visibility)."""
    h = _auth(client)
    ws = _workspace_id(client, h)
    cid = _seed_contact(session_factory, ws, first="Amelia")

    h_read = _read_only_auth(client, session_factory, email="ctm-detail-readonly@example.com")
    assert client.get(f"/omnichannel/contacts/{cid}", headers=h_read).status_code == 200
    assert client.get(f"/omnichannel/contacts/{cid}/messages", headers=h_read).status_code == 200
    # The shared Inbox LIST stays conversations.read-only.
    assert client.get("/omnichannel/contacts", headers=h_read).status_code == 403


def _other_tenant_auth(client, session_factory, slug="other-ctm"):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other CTM", slug=slug, admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()
    return _auth(client, email=f"admin-{slug}@example.com", password="Password123!", tenant_slug=slug)


def test_tenant_isolation_uniform_404(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    seg = client.post(f"{_base(ws)}/contact-segments", headers=h, json={"name": "IsoSeg"}).json()

    h2 = _other_tenant_auth(client, session_factory)
    assert client.get(f"{_base(ws)}/contacts", headers=h2).status_code == 404
    assert client.get(f"{_base(ws)}/contact-segments", headers=h2).status_code == 404
    assert client.post(f"{_base(ws)}/contact-segments", headers=h2, json={"name": "x"}).status_code == 404
    assert client.patch(f"{_base(ws)}/contact-segments/{seg['id']}", headers=h2, json={"name": "y"}).status_code == 404
    assert client.delete(f"{_base(ws)}/contact-segments/{seg['id']}", headers=h2).status_code == 404


def test_segment_belonging_to_another_workspace_is_404(client, session_factory):
    """A segment id resolved against a DIFFERENT (same-tenant) workspace must
    404, never leak - covers the "another workspace" half of AC-CTM-21."""
    from modules.omnichannel.models import Workspace
    from modules.omnichannel.services import statuses

    h = _auth(client)
    ws = _workspace_id(client, h)
    seg = client.post(f"{_base(ws)}/contact-segments", headers=h, json={"name": "OwnWsSeg"}).json()

    db = session_factory()
    other_ws = Workspace(
        tenant_id=DEFAULT_TENANT_ID, name="Second WS",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "WORKSPACE", "ACTIVE"),
    )
    db.add(other_ws)
    db.commit()
    other_ws_id = other_ws.id
    db.close()

    res = client.get(f"{_base(other_ws_id)}/contacts", headers=h, params={"segment": seg["id"]})
    assert res.status_code == 404


# ── AC-CTM-23: batched resolution (tags/channels/lifecycle/custom fields/
# assignee) - one query per kind for a whole page, not per row ──────────────
def test_list_resolution_is_batched_not_per_row(client, session_factory):
    h = _auth(client)
    ws = _workspace_id(client, h)
    client.post(f"{_base(ws)}/contact-fields", headers=h, json={
        "key": "company", "label": "Company", "type": "text",
    })
    wa = _ensure_channel(session_factory, ws, channel_type="WHATSAPP")
    for i in range(12):
        _seed_contact(
            session_factory, ws, first=f"P{i}", assigned_email=ACTIVE_EMAIL,
            tag_names=["Bulk"], lifecycle_key="new_lead",
            custom_fields={"company": f"Co {i}"}, channel_id=wa,
        )

    engine = session_factory.kw["bind"]
    selects = {"n": 0}

    def _before(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            selects["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        res = client.get(f"{_base(ws)}/contacts", headers=h)
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    assert res.status_code == 200
    assert len(res.json()["data"]) == 12
    # A handful of batched SELECTs for the whole page (contacts + previews +
    # unread + tags + lifecycle + custom-field registry + channels + the
    # count query + auth lookups) - NOT ~12 per-row queries.
    assert selects["n"] <= 20, f"expected batched resolution, got {selects['n']} SELECTs"


# ── AC-CTM-43: permissions CSV + manifest bump + grant sweep ─────────────────
def test_new_permissions_granted_to_existing_tenant_admin_on_update(client, session_factory):
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    state = AppStoreService(db)._installed_state(DEFAULT_TENANT_ID, "omnichannel")[1]
    state.installed_version = "0.2.0"
    db.commit()
    db.close()

    db2 = session_factory()
    module, new_state = AppStoreService(db2).update(DEFAULT_TENANT_ID, "omnichannel")
    # Plan 29 S1 bumped the manifest to 0.5.0 - this test pins "the CURRENT
    # manifest version", not a fixed string (updated the same way plan 27/29
    # bumps updated it before).
    assert module.version == "0.5.0"
    assert new_state.installed_version == "0.5.0"
    db2.close()

    h = _auth(client)
    perms = set(client.get("/auth/me", headers=h).json()["permissions"])
    assert {"segments.manage", "contacts.import", "contacts.export"} <= perms


# ── phone_digits backfill (AC-CTM-27 groundwork owned by this slice) ────────
def test_phone_digits_backfill_is_idempotent(client, session_factory):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    h = _auth(client)
    ws = _workspace_id(client, h)
    db = session_factory()
    row = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, first_name="Legacy",
        phone="+60 12-345 6789",
    )
    db.add(row)
    db.commit()
    cid = row.id
    db.close()

    db2 = session_factory()
    stamped = ContactRepository(db2).backfill_phone_digits(DEFAULT_TENANT_ID)
    db2.commit()
    assert stamped >= 1
    refreshed = db2.query(Contact).filter(Contact.id == cid).first()
    assert refreshed.phone_digits == "60123456789"
    db2.close()

    db3 = session_factory()
    stamped_again = ContactRepository(db3).backfill_phone_digits(DEFAULT_TENANT_ID)
    db3.close()
    assert stamped_again == 0


def test_find_by_phone_digits_matches_the_old_scan_including_empty_no_match(client, session_factory):
    """AC-CTM-27 stitch-equivalence: the new indexed lookup returns exactly
    what the O(n) digit-comparison scan used to return, including the
    empty-digits no-match rule."""
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    h = _auth(client)
    ws = _workspace_id(client, h)
    target = _seed_contact(session_factory, ws, first="Stitch", phone="+60 12-345 6789")

    db = session_factory()
    repo = ContactRepository(db)
    found = repo.find_by_phone_in_workspace("60123456789", ws, DEFAULT_TENANT_ID)
    assert found is not None and found.id == target

    none_found = repo.find_by_phone_in_workspace("", ws, DEFAULT_TENANT_ID)
    assert none_found is None
    db.close()
