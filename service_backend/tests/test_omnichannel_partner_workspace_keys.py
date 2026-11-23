"""S8 - per-organisation workspace key issued through the partner routes.

Behaviour: `POST /partner/workspaces/{id}/api-keys` mints an ordinary
`fxw_live_` workspace key through the existing key service (created by
`partner:<keyId>`), shown once; it works on today's public API unchanged;
list and revoke go through the same service, and revoke keeps pausing the
key's webhook endpoints; every route is tenant-scoped with one uniform 404.
Fake values only.
"""
import pytest

from tests.test_omnichannel_api_gateway import _seed_channel
from tests.test_omnichannel_partner_keys import _auth, partner_headers
from tests.test_omnichannel_partner_workspaces import NOT_FOUND, P, put, two_tenants

KEY_NOT_FOUND = {"error": {"code": "api_key_not_found", "message": "API key not found."}}


def mint(client, hdr, wid, name="EcoHub org key"):
    return client.post(f"{P}/workspaces/{wid}/api-keys", json={"name": name}, headers=hdr)


def org(client, session_factory, ext="org-keys", phone="pn-org-keys"):
    hdr = partner_headers(client)
    wid = put(client, hdr, ext).json()["id"]
    _seed_channel(session_factory, wid, phone_number_id=phone)
    return hdr, wid


def test_mint_returns_an_ordinary_workspace_key_once(client, session_factory):
    hdr, wid = org(client, session_factory)
    res = mint(client, hdr, wid)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["fullKey"].startswith("fxw_live_")
    assert body["key"]["workspaceId"] == wid and body["key"]["status"] == "ACTIVE"
    assert body["key"]["maskedKey"].startswith("fxw_live_")
    listed = client.get(f"{P}/workspaces/{wid}/api-keys", headers=hdr)
    assert listed.status_code == 200
    assert [k["id"] for k in listed.json()["data"]] == [body["key"]["id"]]
    assert body["fullKey"] not in listed.text

    from modules.omnichannel.models import PartnerApiKey, WorkspaceApiKey

    db = session_factory()
    row = db.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == body["key"]["id"]).one()
    partner_key = db.query(PartnerApiKey).one()
    assert row.created_by == f"partner:{partner_key.id}"
    assert row.key_hash != body["fullKey"]
    db.close()
    # the dashboard sees the same key
    dash = client.get(f"/omnichannel/workspaces/{wid}/api-keys", headers=_auth(client)).json()["data"]
    assert [k["id"] for k in dash] == [body["key"]["id"]]


def test_the_minted_key_works_on_the_existing_public_api(client, session_factory):
    hdr, wid = org(client, session_factory, ext="org-works", phone="pn-org-works")
    full = mint(client, hdr, wid).json()["fullKey"]
    key_hdr = {"Authorization": f"Bearer {full}"}
    channels = client.get("/api/v1/omnichannel/channels", headers=key_hdr)
    assert channels.status_code == 200, channels.text
    assert [c["id"] for c in channels.json()["data"]] == [
        c["id"] for c in client.get(f"{P}/workspaces/{wid}/channels", headers=hdr).json()["data"]
    ]
    sent = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456789", "type": "template", "template": {"name": "hello_world"}},
        headers=key_hdr,
    )
    assert sent.status_code in (202, 404, 422), sent.text  # reached the send route under this key
    assert sent.status_code != 401
    contacts = client.get("/api/v1/omnichannel/contacts", headers=key_hdr)
    assert contacts.status_code == 200
    # but it is not a partner key
    assert client.get(f"{P}/me", headers=key_hdr).status_code == 401


def test_revoke_stops_the_key_and_pauses_its_endpoints(client, session_factory):
    hdr, wid = org(client, session_factory, ext="org-revoke", phone="pn-org-revoke")
    minted = mint(client, hdr, wid).json()
    key_hdr = {"Authorization": f"Bearer {minted['fullKey']}"}
    hook = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "crm", "url": "https://hooks.example.com/in", "events": ["message.inbound"]},
        headers=key_hdr,
    )
    assert hook.status_code == 201, hook.text
    rev = client.post(f"{P}/workspaces/{wid}/api-keys/{minted['key']['id']}/revoke", headers=hdr)
    assert rev.status_code == 200, rev.text
    assert rev.json()["status"] == "REVOKED" and rev.json()["webhookEndpointCount"] == 0
    assert client.get("/api/v1/omnichannel/channels", headers=key_hdr).status_code == 401

    from modules.omnichannel.models import WebhookEndpoint

    db = session_factory()
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == hook.json()["endpoint"]["id"]).one()
    assert ep.status != "ACTIVE"
    db.close()
    again = client.post(f"{P}/workspaces/{wid}/api-keys/{minted['key']['id']}/revoke", headers=hdr)
    assert again.status_code == 200 and again.json()["revokedAt"] == rev.json()["revokedAt"]


def test_unknown_key_or_a_key_of_another_workspace_is_404(client, session_factory):
    hdr, wid = org(client, session_factory, ext="org-k1", phone="pn-org-k1")
    other = put(client, hdr, "org-k2").json()["id"]
    key_other = mint(client, hdr, other).json()["key"]["id"]
    res = client.post(f"{P}/workspaces/{wid}/api-keys/{key_other}/revoke", headers=hdr)
    assert res.status_code == 404 and res.json() == KEY_NOT_FOUND
    assert client.post(f"{P}/workspaces/{wid}/api-keys/nope/revoke", headers=hdr).json() == KEY_NOT_FOUND


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "x" * 121}])
def test_a_bad_key_name_is_refused(client, session_factory, body):
    hdr, wid = org(client, session_factory, ext="org-name", phone="pn-org-name")
    res = client.post(f"{P}/workspaces/{wid}/api-keys", json=body, headers=hdr)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_another_tenants_workspace_key_cannot_be_revoked(client, session_factory):
    hdr_a, hdr_b, ws_b = two_tenants(client, session_factory, slug="partner-keys-b3")
    key_b = mint(client, hdr_b, ws_b).json()
    res = client.post(f"{P}/workspaces/{ws_b}/api-keys/{key_b['key']['id']}/revoke", headers=hdr_a)
    assert res.status_code == 404 and res.json() == NOT_FOUND
    listed = client.get(f"{P}/workspaces/{ws_b}/api-keys", headers=hdr_b).json()["data"]
    assert listed[0]["status"] == "ACTIVE"


def test_a_trashed_workspace_is_404_on_every_key_route(client, session_factory):
    from app.models import DEFAULT_TENANT_ID
    from modules.omnichannel.services.workspace_service import WorkspaceService

    hdr, wid = org(client, session_factory, ext="org-keys-trash", phone="pn-org-keys-trash")
    minted = mint(client, hdr, wid).json()
    db = session_factory()
    WorkspaceService(db).trash([wid], DEFAULT_TENANT_ID)
    db.close()
    assert mint(client, hdr, wid).json() == NOT_FOUND
    listed = client.get(f"{P}/workspaces/{wid}/api-keys", headers=hdr)
    assert listed.status_code == 404 and listed.json() == NOT_FOUND
    rev = client.post(f"{P}/workspaces/{wid}/api-keys/{minted['key']['id']}/revoke", headers=hdr)
    assert rev.status_code == 404 and rev.json() == NOT_FOUND


def test_another_tenants_workspace_cannot_be_listed_or_minted_into(client, session_factory):
    hdr_a, hdr_b, ws_b = two_tenants(client, session_factory, slug="partner-keys-b4")
    key_b = mint(client, hdr_b, ws_b).json()
    minted = mint(client, hdr_a, ws_b)
    assert minted.status_code == 404 and minted.json() == NOT_FOUND
    listed = client.get(f"{P}/workspaces/{ws_b}/api-keys", headers=hdr_a)
    assert listed.status_code == 404 and listed.json() == NOT_FOUND
    # the workspace check runs before the key lookup: an unknown key is still workspace_not_found
    assert client.post(f"{P}/workspaces/{ws_b}/api-keys/nope/revoke", headers=hdr_a).json() == NOT_FOUND
    assert [k["id"] for k in client.get(f"{P}/workspaces/{ws_b}/api-keys", headers=hdr_b).json()["data"]] == [
        key_b["key"]["id"]
    ]
