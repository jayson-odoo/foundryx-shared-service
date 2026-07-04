"""WhatsApp template management tests (plan 07 Slice B1).

Transform round-trip, validate_doc matrix, draft→submit→sync→edit→delete (dev
stubs), webhook application (idempotent), tenant-scoping + perm gates.
"""
import pytest

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password
from modules.omnichannel import template_schemas as ts
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ── transform parity (round-trip) ────────────────────────────────────────────
def test_transform_round_trip_all_parts():
    doc = ts.WaTemplateDoc(
        name="order_update", category="UTILITY", language="en_US",
        header=ts.WaHeader(format="TEXT", text="Hi {{1}}", example="Sam"),
        body=ts.WaBody(text="Order {{1}} is {{2}}.", examples=["A1", "shipped"]),
        footer=ts.WaFooter(text="Thanks"),
        buttons=[
            ts.WaButton(type="QUICK_REPLY", text="Track"),
            ts.WaButton(type="URL", text="Open", url="https://x.com/{{1}}", example="id1"),
            ts.WaButton(type="PHONE_NUMBER", text="Call", phoneNumber="+60123456789"),
            ts.WaButton(type="COPY_CODE", example="SAVE10"),
        ],
    )
    comps = ts.to_meta_components(doc)
    back = ts.from_meta_components(comps, name="order_update", category="UTILITY", language="en_US")
    assert back.header.format == "TEXT" and back.header.example == "Sam"
    assert back.body.text == "Order {{1}} is {{2}}." and back.body.examples == ["A1", "shipped"]
    assert back.footer.text == "Thanks"
    assert [b.type for b in back.buttons] == ["QUICK_REPLY", "URL", "PHONE_NUMBER", "COPY_CODE"]
    assert back.buttons[1].url == "https://x.com/{{1}}" and back.buttons[1].example == "id1"
    assert back.buttons[2].phoneNumber == "+60123456789"
    assert back.buttons[3].example == "SAVE10"


def test_transform_media_header():
    doc = ts.WaTemplateDoc(
        name="promo", category="MARKETING", language="en",
        header=ts.WaHeader(format="IMAGE", sampleKey="conn:1:abc"),
        body=ts.WaBody(text="Big news!", examples=[]),
    )
    comps = ts.to_meta_components(doc)
    header = next(c for c in comps if c["type"] == "HEADER")
    assert header["format"] == "IMAGE"
    assert header["example"]["header_handle"] == ["conn:1:abc"]


# ── validate_doc matrix ──────────────────────────────────────────────────────
def _valid_doc(**over):
    base = dict(name="good_name", category="UTILITY", language="en",
                body=ts.WaBody(text="Hello", examples=[]))
    base.update(over)
    return ts.WaTemplateDoc(**base)


def test_validate_bad_name():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(name="Bad Name!"))
    assert "name" in e.value.detail["fieldErrors"]


def test_validate_dup_name():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(name="taken"), existing_names={"taken"})
    assert "name" in e.value.detail["fieldErrors"]


def test_validate_bad_category():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(category="NEWS"))
    assert "category" in e.value.detail["fieldErrors"]


def test_validate_empty_body():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(body=ts.WaBody(text="  ", examples=[])))
    assert "body" in e.value.detail["fieldErrors"]


def test_validate_sample_mismatch():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(body=ts.WaBody(text="Hi {{1}} {{2}}", examples=["only one"])))
    assert "body" in e.value.detail["fieldErrors"]


def test_validate_sample_match_ok():
    ts.validate_doc(_valid_doc(body=ts.WaBody(text="Hi {{1}} {{2}}", examples=["a", "b"])))


def test_validate_non_sequential_vars():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(body=ts.WaBody(text="Hi {{1}} and {{3}}", examples=["a", "b"])))
    assert "body" in e.value.detail["fieldErrors"]


def test_text_header_drops_stale_example_when_no_var():
    doc = ts.WaTemplateDoc(
        name="hdr", category="UTILITY", language="en",
        header=ts.WaHeader(format="TEXT", text="No variables here", example="stale"),
        body=ts.WaBody(text="Hi", examples=[]),
    )
    header = next(c for c in ts.to_meta_components(doc) if c["type"] == "HEADER")
    assert "example" not in header  # stale example must not reach Meta


def test_validate_button_bad_url():
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(buttons=[ts.WaButton(type="URL", text="x", url="ftp://no")]))
    assert "buttons" in e.value.detail["fieldErrors"]


def test_validate_button_limit():
    btns = [ts.WaButton(type="QUICK_REPLY", text=f"b{i}") for i in range(11)]
    with pytest.raises(Exception) as e:
        ts.validate_doc(_valid_doc(buttons=btns))
    assert "buttons" in e.value.detail["fieldErrors"]


# ── API lifecycle (dev stubs) ────────────────────────────────────────────────
def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> dict:
    body = {"email": email, "password": password}
    if tenant_slug:
        body["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=body)
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _default_workspace_id(client, h) -> str:
    data = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    return next(w["id"] for w in data if w["isDefault"])


def _channel(client, h) -> str:
    res = client.post(
        "/omnichannel/onboarding/oauth-callback", headers=h,
        json={"workspaceId": _default_workspace_id(client, h), "code": "c", "wabaId": "waba-1",
              "phoneNumberId": "pn-1", "displayPhoneNumber": "+1", "businessName": "T"},
    )
    return res.json()["id"]


_DRAFT = {
    "name": "order_update",
    "category": "UTILITY",
    "language": "en_US",
    "body": {"text": "Order {{1}} is ready.", "examples": ["A1"]},
    "footer": {"text": "Thanks"},
    "buttons": [{"type": "QUICK_REPLY", "text": "Track"}],
}


def test_draft_submit_sync_edit_delete_lifecycle(client):
    h = _auth(client)
    cid = _channel(client, h)
    base = f"/omnichannel/channels/{cid}/templates"

    # save draft → LOCAL_DRAFT, no meta id
    created = client.post(base, headers=h, json=_DRAFT)
    assert created.status_code == 201
    tid = created.json()["id"]
    assert created.json()["status"] == "LOCAL_DRAFT"
    assert created.json()["metaTemplateId"] is None
    assert created.json()["doc"]["body"]["text"] == "Order {{1}} is ready."

    # list shows it
    listed = client.get(f"{base}/manage", headers=h).json()
    assert any(t["id"] == tid for t in listed["data"])

    # submit (dev) → PENDING + fake meta id
    sub = client.post(f"{base}/{tid}/submit", headers=h)
    assert sub.status_code == 200
    assert sub.json()["status"] == "PENDING"
    assert sub.json()["metaTemplateId"]

    # submit again → 409 (only a draft can submit)
    assert client.post(f"{base}/{tid}/submit", headers=h).status_code == 409

    # sync (dev) promotes PENDING → APPROVED
    synced = client.post(f"{base}/sync", headers=h)
    assert synced.status_code == 200
    row = next(t for t in synced.json()["data"] if t["id"] == tid)
    assert row["status"] == "APPROVED"
    assert row["quality"] == "GREEN"

    # edit approved → components-only → back to PENDING
    edited = client.patch(f"{base}/{tid}", headers=h, json={**_DRAFT, "body": {"text": "Order {{1}} updated.", "examples": ["A1"]}})
    assert edited.status_code == 200
    assert edited.json()["status"] == "PENDING"

    # delete → gone
    assert client.delete(f"{base}/{tid}", headers=h).status_code == 204
    assert all(t["id"] != tid for t in client.get(f"{base}/manage", headers=h).json()["data"])


def test_draft_validation_422(client):
    h = _auth(client)
    cid = _channel(client, h)
    bad = {**_DRAFT, "body": {"text": "Hi {{1}} {{2}}", "examples": ["only one"]}}
    res = client.post(f"/omnichannel/channels/{cid}/templates", headers=h, json=bad)
    assert res.status_code == 422
    assert "body" in res.json()["detail"]["fieldErrors"]


def test_edit_pending_blocked_409(client):
    h = _auth(client)
    cid = _channel(client, h)
    base = f"/omnichannel/channels/{cid}/templates"
    tid = client.post(base, headers=h, json=_DRAFT).json()["id"]
    client.post(f"{base}/{tid}/submit", headers=h)  # → PENDING
    res = client.patch(f"{base}/{tid}", headers=h, json=_DRAFT)
    assert res.status_code == 409


# ── webhook application ──────────────────────────────────────────────────────
def test_apply_webhook_event_idempotent(client, session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services.template_management_service import TemplateManagementService

    h = _auth(client)
    cid = _channel(client, h)
    base = f"/omnichannel/channels/{cid}/templates"
    tid = client.post(base, headers=h, json=_DRAFT).json()["id"]
    mid = client.post(f"{base}/{tid}/submit", headers=h).json()["metaTemplateId"]

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == cid).first()
    svc = TemplateManagementService(db)
    event = {"kind": "template_status", "message_template_id": str(mid), "name": "order_update",
             "language": "en_US", "status": "REJECTED", "reason": "INVALID_FORMAT"}
    assert svc.apply_webhook_event(channel, event) is True
    assert svc.apply_webhook_event(channel, event) is True  # idempotent — no error
    db.close()

    row = client.get(f"{base}/manage/{tid}", headers=h).json()
    assert row["status"] == "REJECTED"
    assert row["rejectedReason"] == "INVALID_FORMAT"


def test_apply_webhook_malformed_safe(client, session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services.template_management_service import TemplateManagementService

    h = _auth(client)
    cid = _channel(client, h)
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == cid).first()
    # No matching row + junk payload → False, never raises.
    assert TemplateManagementService(db).apply_webhook_event(channel, {"kind": "template_status"}) is False
    db.close()


# ── tenant scoping + perm gates ──────────────────────────────────────────────
def test_template_cross_tenant_404(client, session_factory):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h = _auth(client)
    cid = _channel(client, h)
    db = session_factory()
    other = TenantService(db).provision(
        name="Other", slug="otherco-tpl", admin_email="other-tpl@example.com",
        admin_password="Password123!", admin_name="O",
    )
    db.flush()
    AppStoreService(db).install(other.id, "omnichannel")
    db.commit()
    db.close()
    h2 = _auth(client, email="other-tpl@example.com", password="Password123!", tenant_slug="otherco-tpl")
    assert client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=h2).status_code == 404


def test_template_permission_gates(client, session_factory):
    db = session_factory()
    db.add(User(tenant_id=DEFAULT_TENANT_ID, email="norole-tpl@example.com", name="N",
                password=hash_password("Password123!"), status=UserStatus.ACTIVE.value))
    db.commit()
    db.close()
    h = _auth(client)
    cid = _channel(client, h)
    hn = _auth(client, email="norole-tpl@example.com", password="Password123!")
    assert client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=hn).status_code == 403
    assert client.post(f"/omnichannel/channels/{cid}/templates", headers=hn, json=_DRAFT).status_code == 403
