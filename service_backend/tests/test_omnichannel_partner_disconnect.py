"""FSS-3 - partner channel disconnect.

Behaviour, through the API: `POST /partner/workspaces/{workspaceId}/channels/
{channelId}/disconnect` disconnects one channel of a workspace of the key's
client app exactly as the dashboard disconnect does (trashed, inactive,
`channel.updated`), and answers the workspace's remaining channel list; a
repeat, an unknown channel, a channel of another workspace, and anything of
another tenant or client app answer a uniform 404; the dashboard disconnect is
unchanged. Fake values only.
"""
from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _default_workspace_id, _seed_channel
from tests.test_omnichannel_client_apps import _key_for, _new_app
from tests.test_omnichannel_partner_keys import _auth, other_tenant, partner_headers

P = "/api/v1/omnichannel/partner"
WS_NOT_FOUND = {"error": {"code": "workspace_not_found", "message": "Workspace not found."}}
CH_NOT_FOUND = {"error": {"code": "channel_not_found", "message": "Channel not found."}}


def put(client, hdr, ext):
    res = client.put(f"{P}/workspaces/{ext}", json={"name": f"Org {ext}"}, headers=hdr)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def disconnect(client, hdr, ws, ch):
    return client.post(f"{P}/workspaces/{ws}/channels/{ch}/disconnect", headers=hdr)


def channel_row(session_factory, cid):
    from modules.omnichannel.models import Channel

    db = session_factory()
    row = db.get(Channel, cid)
    db.expunge(row)
    db.close()
    return row


def test_disconnect_trashes_the_channel_and_answers_the_remaining_list(client, session_factory, monkeypatch):
    from modules.omnichannel.services import channel_service

    events = []
    monkeypatch.setattr(channel_service, "emit_channel_updated", lambda db, c: events.append(c.id))
    hdr = partner_headers(client)
    ws = put(client, hdr, "org-1")
    keep = _seed_channel(session_factory, ws, phone_number_id="pn-keep")
    gone = _seed_channel(session_factory, ws, phone_number_id="pn-gone")

    res = disconnect(client, hdr, ws, gone)
    assert res.status_code == 200, res.text
    assert [c["id"] for c in res.json()["data"]] == [keep]
    row = channel_row(session_factory, gone)
    assert row.is_trashed is True and row.is_active is False
    assert events == [gone]
    listed = client.get(f"{P}/workspaces/{ws}/channels", headers=hdr).json()["data"]
    assert [c["id"] for c in listed] == [keep]
    # The number is free again for a new connect (service-wide uniqueness ignores trashed rows).
    assert channel_row(session_factory, keep).is_trashed is False


def test_a_repeat_or_unknown_channel_is_404(client, session_factory):
    hdr = partner_headers(client)
    ws = put(client, hdr, "org-1")
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-twice")
    assert disconnect(client, hdr, ws, ch).status_code == 200
    again = disconnect(client, hdr, ws, ch)
    assert again.status_code == 404 and again.json() == CH_NOT_FOUND
    unknown = disconnect(client, hdr, ws, "no-such-channel")
    assert unknown.status_code == 404 and unknown.json() == CH_NOT_FOUND


def test_a_channel_of_another_workspace_is_404_and_untouched(client, session_factory):
    hdr = partner_headers(client)
    ws1 = put(client, hdr, "org-1")
    ws2 = put(client, hdr, "org-2")
    ch2 = _seed_channel(session_factory, ws2, phone_number_id="pn-other-ws")
    res = disconnect(client, hdr, ws1, ch2)
    assert res.status_code == 404 and res.json() == CH_NOT_FOUND
    assert channel_row(session_factory, ch2).is_trashed is False
    # A key of another client app cannot reach the tenant's "General" workspace.
    _, hdr_eco = _key_for(client, _new_app(session_factory, "Ecohub"), name="Eco")
    general = _default_workspace_id(session_factory)
    ch_general = _seed_channel(session_factory, general, phone_number_id="pn-general")
    res = disconnect(client, hdr_eco, general, ch_general)
    assert res.status_code == 404 and res.json() == WS_NOT_FOUND
    assert channel_row(session_factory, ch_general).is_trashed is False


def test_another_tenant_or_client_app_gets_the_uniform_404(client, session_factory):
    _, hdr_eco = _key_for(client, _new_app(session_factory, "Ecohub"), name="Eco")
    _, hdr_fuji = _key_for(client, _new_app(session_factory, "MyFuji Platform"), name="Fuji")
    ws = put(client, hdr_eco, "org-eco")
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-scope")
    _, admin_b = other_tenant(client, session_factory, slug="disconnect-b")
    hdr_b = partner_headers(client, admin_b, name="B")
    for hdr in (hdr_fuji, hdr_b):
        res = disconnect(client, hdr, ws, ch)
        assert res.status_code == 404 and res.json() == WS_NOT_FOUND
    assert channel_row(session_factory, ch).is_trashed is False
    assert disconnect(client, hdr_eco, ws, ch).status_code == 200


def test_a_disabled_client_app_is_refused(client, session_factory):
    from modules.omnichannel.models import ClientApp

    hdr = partner_headers(client)
    ws = put(client, hdr, "org-1")
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-disabled")
    db = session_factory()
    db.query(ClientApp).filter_by(tenant_id=DEFAULT_TENANT_ID).update({"status": "DISABLED"})
    db.commit()
    db.close()
    res = disconnect(client, hdr, ws, ch)
    assert res.status_code == 403 and res.json()["error"]["code"] == "client_app_disabled"
    assert channel_row(session_factory, ch).is_trashed is False


def test_the_dashboard_disconnect_is_unchanged(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-dash")
    res = client.post("/omnichannel/channels/disconnect", json={"ids": [ch]}, headers=_auth(client))
    assert res.status_code in (200, 204), res.text
    assert channel_row(session_factory, ch).is_trashed is True
