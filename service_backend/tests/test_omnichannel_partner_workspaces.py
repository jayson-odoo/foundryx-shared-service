"""S7 - partner workspaces, idempotent by `externalOrgId`.

Behaviour: `PUT /partner/workspaces/{externalOrgId}` creates the organisation's
workspace in the key's tenant on the first call and returns the same row on
every repeat (also when two first calls race); reads list, get and channels;
every route is scoped to the key's tenant and answers one uniform 404 for
another tenant's ids; `externalOrgId` is validated; the dashboard workspace
routes are unchanged; migration chain. Fake values only.
"""
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _seed_channel
from tests.test_omnichannel_partner_keys import _auth, other_tenant, partner_headers

P = "/api/v1/omnichannel/partner"
ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "alembic"
NOT_FOUND = {"error": {"code": "workspace_not_found", "message": "Workspace not found."}}


def put(client, hdr, ext, name="Acme Sdn Bhd"):
    return client.put(f"{P}/workspaces/{ext}", json={"name": name}, headers=hdr)


def two_tenants(client, session_factory, slug="partner-ws-b"):
    """(A partner headers, B partner headers, B workspace id with a channel)."""
    _, admin_b = other_tenant(client, session_factory, slug=slug)
    hdr_a = partner_headers(client, name="A")
    hdr_b = partner_headers(client, admin_b, name="B")
    ws_b = put(client, hdr_b, "org-b").json()["id"]
    return hdr_a, hdr_b, ws_b


# ── create and idempotency ───────────────────────────────────────────────────
def test_first_put_creates_and_repeats_return_the_same_workspace(client, session_factory):
    hdr = partner_headers(client)
    first = put(client, hdr, "org-42")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["externalOrgId"] == "org-42"
    assert body["name"] == "Acme Sdn Bhd"
    assert body["status"] == "ACTIVE"
    assert body["channels"] == []
    assert body["id"] and body["createdAt"]
    again = put(client, hdr, "org-42")
    assert again.status_code == 200 and again.json() == body

    from modules.omnichannel.models import Workspace

    db = session_factory()
    rows = db.query(Workspace).filter(Workspace.external_ref == "org-42").all()
    assert len(rows) == 1 and rows[0].tenant_id == DEFAULT_TENANT_ID and rows[0].is_default is False
    db.close()


def test_created_workspace_gets_the_dashboard_seeding(client, session_factory):
    hdr = partner_headers(client)
    wid = put(client, hdr, "org-seeded").json()["id"]
    res = client.get(f"/omnichannel/workspaces/{wid}", headers=_auth(client))
    assert res.status_code == 200 and res.json()["name"] == "Acme Sdn Bhd"
    from modules.omnichannel.models import CloseReason

    db = session_factory()
    assert db.query(CloseReason).filter(CloseReason.workspace_id == wid).count() > 0
    db.close()


def test_put_with_a_new_name_renames_the_same_workspace(client):
    hdr = partner_headers(client)
    wid = put(client, hdr, "org-rename", name="Old").json()["id"]
    res = put(client, hdr, "org-rename", name="  New name  ")
    assert res.status_code == 200
    assert res.json()["id"] == wid and res.json()["name"] == "New name"


def test_a_concurrent_first_put_reads_back_the_winner(client, session_factory, monkeypatch):
    """Two first calls race: the loser's read misses, its insert hits the
    unique index, it rolls back and returns the winner's row."""
    from modules.omnichannel.repositories.workspace_repository import WorkspaceRepository

    hdr = partner_headers(client)
    winner = put(client, hdr, "org-race").json()
    real = WorkspaceRepository.get_live_by_external_ref
    calls = {"n": 0}

    def stale_first_read(self, tenant_id, external_ref):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the other request had not committed yet
        return real(self, tenant_id, external_ref)

    monkeypatch.setattr(WorkspaceRepository, "get_live_by_external_ref", stale_first_read)
    loser = put(client, hdr, "org-race")
    assert loser.status_code == 200, loser.text
    assert loser.json()["id"] == winner["id"]
    assert calls["n"] == 2

    from modules.omnichannel.models import Workspace

    db = session_factory()
    assert db.query(Workspace).filter(Workspace.external_ref == "org-race").count() == 1
    db.close()


def test_the_unique_index_rejects_a_second_live_row_but_allows_after_trash(session_factory):
    from sqlalchemy.exc import IntegrityError

    from modules.omnichannel.models import Workspace

    db = session_factory()
    db.add(Workspace(tenant_id=DEFAULT_TENANT_ID, name="a", external_ref="dup"))
    db.commit()
    db.add(Workspace(tenant_id=DEFAULT_TENANT_ID, name="b", external_ref="dup"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.query(Workspace).filter(Workspace.external_ref == "dup").update({"is_trashed": True})
    db.add(Workspace(tenant_id=DEFAULT_TENANT_ID, name="c", external_ref="dup"))
    db.commit()  # a trashed row no longer holds the ref
    db.add(Workspace(tenant_id="another-tenant", name="d", external_ref="dup"))
    db.commit()  # the same ref in another tenant is a different organisation
    db.close()


# ── reads ────────────────────────────────────────────────────────────────────
def test_list_filters_by_external_org_id_and_pages(client):
    hdr = partner_headers(client)
    ids = [put(client, hdr, f"org-list-{i}", name=f"Org {i}").json()["id"] for i in range(3)]
    one = client.get(f"{P}/workspaces", params={"externalOrgId": "org-list-1"}, headers=hdr)
    assert one.status_code == 200
    assert [w["id"] for w in one.json()["data"]] == [ids[1]] and one.json()["total"] == 1
    page = client.get(f"{P}/workspaces", params={"pageSize": 2, "page": 0}, headers=hdr).json()
    assert page["pageSize"] == 2 and len(page["data"]) == 2
    # the tenant's default (dashboard) workspace is listed too, with externalOrgId null
    everything = client.get(f"{P}/workspaces", params={"pageSize": 100}, headers=hdr).json()
    assert everything["total"] == 4
    assert {w["externalOrgId"] for w in everything["data"]} == {None, "org-list-0", "org-list-1", "org-list-2"}
    none = client.get(f"{P}/workspaces", params={"externalOrgId": "nobody"}, headers=hdr).json()
    assert none["data"] == [] and none["total"] == 0


def test_get_and_channels_return_the_public_channel_list(client, session_factory):
    hdr = partner_headers(client)
    wid = put(client, hdr, "org-ch").json()["id"]
    _seed_channel(session_factory, wid, phone_number_id="pn-partner-ch")
    got = client.get(f"{P}/workspaces/{wid}", headers=hdr)
    assert got.status_code == 200
    channels = client.get(f"{P}/workspaces/{wid}/channels", headers=hdr)
    assert channels.status_code == 200
    assert got.json()["channels"] == channels.json()["data"]
    item = channels.json()["data"][0]
    assert item["channelType"] == "WHATSAPP" and item["isDefault"] is True
    assert "phoneNumberId" not in item and "wabaId" not in item and "credentials" not in str(item)
    assert put(client, hdr, "org-ch").json()["channels"] == channels.json()["data"]


def test_a_trashed_workspace_is_404_and_put_then_starts_a_new_one(client, session_factory):
    from modules.omnichannel.services.workspace_service import WorkspaceService

    hdr = partner_headers(client)
    wid = put(client, hdr, "org-trash").json()["id"]
    db = session_factory()
    WorkspaceService(db).trash([wid], DEFAULT_TENANT_ID)
    db.close()
    assert client.get(f"{P}/workspaces/{wid}", headers=hdr).json() == NOT_FOUND
    fresh = put(client, hdr, "org-trash").json()
    assert fresh["id"] != wid


# ── isolation ────────────────────────────────────────────────────────────────
# Every partner route that takes a workspace id. Paths use `{ws}`.
ID_ROUTES = [
    ("GET", "/workspaces/{ws}", None),
    ("GET", "/workspaces/{ws}/channels", None),
    ("GET", "/workspaces/{ws}/api-keys", None),
    ("POST", "/workspaces/{ws}/api-keys", {"name": "iso"}),
    ("POST", "/workspaces/{ws}/api-keys/any-key-id/revoke", None),
]


@pytest.mark.parametrize("method,path,body", ID_ROUTES)
def test_every_route_answers_the_same_404_for_another_tenants_workspace(client, session_factory, method, path, body):
    hdr_a, hdr_b, ws_b = two_tenants(client, session_factory)
    _seed_channel(session_factory, ws_b, phone_number_id="pn-iso-b")
    url = P + path.format(ws=ws_b)
    own = client.request(method, url, headers=hdr_b, json=body)
    assert own.status_code != 404 or own.json() != NOT_FOUND, own.text  # control: B reaches its own workspace
    cross = client.request(method, url, headers=hdr_a, json=body)
    unknown = client.request(method, P + path.format(ws="00000000-0000-0000-0000-00000000dead"), headers=hdr_a, json=body)
    assert cross.status_code == 404 and unknown.status_code == 404
    assert cross.json() == unknown.json() == NOT_FOUND


def test_list_and_put_never_reach_another_tenant(client, session_factory):
    hdr_a, hdr_b, ws_b = two_tenants(client, session_factory, slug="partner-ws-b2")
    listed = client.get(f"{P}/workspaces", params={"externalOrgId": "org-b"}, headers=hdr_a).json()
    assert listed["data"] == []
    mine = put(client, hdr_a, "org-b").json()  # the same external id in A is A's own org
    assert mine["id"] != ws_b
    assert client.get(f"{P}/workspaces/{ws_b}", headers=hdr_b).json()["name"] == "Acme Sdn Bhd"


# ── validation ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ext", ["-starts-with-dash", "has space", "x" * 129, "bad%23hash", "a%2Fb", "%2Fslash", "ü-umlaut"])
def test_invalid_external_org_ids_are_refused(client, ext):
    hdr = partner_headers(client)
    res = client.put(f"{P}/workspaces/{ext}", json={"name": "x"}, headers=hdr)
    assert res.status_code in (404, 422), res.text
    if res.status_code == 422:
        assert res.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("ext", ["a", "org_1.2:3-4", "x" * 128, "A1B2"])
def test_valid_external_org_ids_are_accepted(client, ext):
    assert put(client, partner_headers(client), ext).status_code == 200


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 201}])
def test_a_blank_or_long_name_is_refused(client, body):
    res = client.put(f"{P}/workspaces/org-name", json=body, headers=partner_headers(client))
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_list_query_external_org_id_is_validated(client):
    res = client.get(f"{P}/workspaces", params={"externalOrgId": "bad id"}, headers=partner_headers(client))
    assert res.status_code == 422


def test_workspace_routes_need_a_partner_key(client, session_factory):
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

    workspace_key = _mint(client, _default_workspace_id(session_factory)).json()["fullKey"]
    res = put(client, {"Authorization": f"Bearer {workspace_key}"}, "org-x")
    assert res.status_code == 401 and res.json()["error"]["code"] == "invalid_api_key"


# ── dashboard unchanged ──────────────────────────────────────────────────────
def test_dashboard_workspace_routes_are_unchanged(client):
    h = _auth(client)
    created = client.post("/omnichannel/workspaces", json={"name": "Dash"}, headers=h)
    assert created.status_code in (200, 201), created.text
    assert set(created.json()) == {
        "id", "tenantId", "name", "status", "channelCount", "memberCount",
        "isDefault", "isTrashed", "createdAt", "updatedAt",
    }
    listed = client.get("/omnichannel/workspaces", headers=h).json()
    assert all("externalRef" not in w and "externalOrgId" not in w for w in listed["data"])


# ── dashboard restore of a partner workspace ─────────────────────────────────
W = "/omnichannel/workspaces"
IN_USE = "workspace_external_ref_in_use"


def _trash(client, h, *ids):
    res = client.post(f"{W}/trash", json={"ids": list(ids)}, headers=h)
    assert res.status_code == 204, res.text


def _is_trashed(client, h, wid):
    return client.get(f"{W}/{wid}", headers=h).json()["isTrashed"]


def _replaced(client, hdr, h, ext):
    """(old trashed workspace id, new live workspace id) for one organisation."""
    old = put(client, hdr, ext).json()["id"]
    _trash(client, h, old)
    new = put(client, hdr, ext).json()["id"]
    assert new != old
    return old, new


def test_restore_of_a_partner_workspace_whose_ref_is_free_succeeds(client):
    hdr, h = partner_headers(client), _auth(client)
    wid = put(client, hdr, "org-back").json()["id"]
    _trash(client, h, wid)
    res = client.post(f"{W}/restore", json={"ids": [wid]}, headers=h)
    assert res.status_code == 204, res.text
    assert _is_trashed(client, h, wid) is False
    assert client.get(f"{P}/workspaces/{wid}", headers=hdr).status_code == 200


def test_restore_is_refused_while_another_live_workspace_holds_the_ref(client):
    hdr, h = partner_headers(client), _auth(client)
    old, new = _replaced(client, hdr, h, "org-held")
    res = client.post(f"{W}/restore", json={"ids": [old]}, headers=h)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == IN_USE
    assert res.json()["detail"]["workspaceId"] == old
    assert _is_trashed(client, h, old) is True
    assert _is_trashed(client, h, new) is False
    listed = client.get(f"{P}/workspaces", params={"externalOrgId": "org-held"}, headers=hdr).json()
    assert [w["id"] for w in listed["data"]] == [new]


def test_bulk_restore_with_a_conflict_names_it_and_restores_nothing(client):
    hdr, h = partner_headers(client), _auth(client)
    old, new = _replaced(client, hdr, h, "org-bulk")
    plain = client.post(W, json={"name": "Plain"}, headers=h).json()["id"]
    _trash(client, h, plain)
    res = client.post(f"{W}/restore", json={"ids": [plain, old]}, headers=h)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == IN_USE
    assert res.json()["detail"]["workspaceId"] == old
    assert _is_trashed(client, h, plain) is True and _is_trashed(client, h, old) is True
    assert _is_trashed(client, h, new) is False
    ok = client.post(f"{W}/restore", json={"ids": [plain]}, headers=h)
    assert ok.status_code == 204 and _is_trashed(client, h, plain) is False


def test_bulk_restore_of_two_trashed_rows_with_the_same_ref_is_refused(client):
    hdr, h = partner_headers(client), _auth(client)
    first, second = _replaced(client, hdr, h, "org-twice")
    _trash(client, h, second)
    res = client.post(f"{W}/restore", json={"ids": [first, second]}, headers=h)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["code"] == IN_USE
    assert res.json()["detail"]["workspaceId"] in {first, second}
    assert _is_trashed(client, h, first) is True and _is_trashed(client, h, second) is True


def test_a_restore_that_loses_the_race_at_commit_is_a_409(client, monkeypatch):
    from modules.omnichannel.repositories.workspace_repository import WorkspaceRepository

    hdr, h = partner_headers(client), _auth(client)
    old, new = _replaced(client, hdr, h, "org-late")
    real = WorkspaceRepository.get_live_by_external_ref
    calls = {"n": 0}

    def stale_first_read(self, tenant_id, external_ref):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the other workspace had not committed yet
        return real(self, tenant_id, external_ref)

    monkeypatch.setattr(WorkspaceRepository, "get_live_by_external_ref", stale_first_read)
    res = client.post(f"{W}/restore", json={"ids": [old]}, headers=h)
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == {
        "code": IN_USE,
        "message": "Another live workspace already uses this partner organisation id.",
        "workspaceId": old,
    }
    assert calls["n"] == 2
    monkeypatch.undo()
    assert _is_trashed(client, h, old) is True and _is_trashed(client, h, new) is False


# ── migration chain ──────────────────────────────────────────────────────────
def test_external_ref_migration_revises_the_omnichannel_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(ALEMBIC_DIR))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    rev = script.get_revision("0031_omni_workspace_external_ref")
    assert rev.down_revision == "0030_omni_delivery_history_ix"
    assert len(rev.revision) <= 32
    chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
    assert rev.revision in chain
