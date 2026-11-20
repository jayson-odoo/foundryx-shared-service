"""Client apps (migration 0032): a real parent for workspaces and partner keys.

Behaviour: the fill-in gives every existing workspace a client app, grouping
same-name workspaces of a tenant (trimmed, case-insensitive, live or trashed)
under one client app named after the live one; exactly one default client app
per tenant (the default workspace's), which partner keys join; idempotent and
never touching other tenants; a NULL parent (written by an older running
version) is resolved by the same rule and persisted; a dashboard-created
workspace gets the client app named after it, a partner-created one the
calling key's, module install's "General" its own default one; partner key
mint takes an optional `clientAppId`; a read-only client-app list; partner
routes scoped to the key's client app with the uniform 404; external_ref
unique per client app; DISABLED blocks partner routes only; moving a workspace
keeps its workspace keys working; uninstall order; the Alembic migration and
the `create_schema_and_tables` mirror agree. Fake values only.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint, _seed_channel
from tests.test_omnichannel_contacts_module import _no_perm_auth
from tests.test_omnichannel_partner_keys import _auth, other_tenant, partner_headers

P = "/api/v1/omnichannel/partner"
KEYS = "/omnichannel/partner-keys"
APPS = "/omnichannel/client-apps"
VERSIONS = Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "alembic" / "versions"
MIGRATION = VERSIONS / "0032_omni_client_apps.py"
NOT_FOUND = {"error": {"code": "workspace_not_found", "message": "Workspace not found."}}
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── helpers ──────────────────────────────────────────────────────────────────
def _models():
    from modules.omnichannel import models

    return models


def _service(db):
    from modules.omnichannel.services.client_app_service import ClientAppService

    return ClientAppService(db)


def _strip_parents(db, tenant_id):
    """Put a tenant back to its pre-0032 shape: no client apps, NULL parents."""
    m = _models()
    db.query(m.Workspace).filter(m.Workspace.tenant_id == tenant_id).update({"client_app_id": None})
    db.query(m.PartnerApiKey).filter(m.PartnerApiKey.tenant_id == tenant_id).update(
        {"client_app_id": None}
    )
    db.query(m.ClientApp).filter(m.ClientApp.tenant_id == tenant_id).delete()
    db.commit()


def _apps(db, tenant_id):
    m = _models()
    return db.query(m.ClientApp).filter(m.ClientApp.tenant_id == tenant_id).all()


def _app_of(db, workspace_id):
    m = _models()
    ws = db.get(m.Workspace, workspace_id)
    db.refresh(ws)
    return db.get(m.ClientApp, ws.client_app_id) if ws.client_app_id else None


def _ws(db, tenant_id, name, minutes, *, trashed=False, default=False, ext=None):
    m = _models()
    ws = m.Workspace(
        tenant_id=tenant_id, name=name, is_trashed=trashed, is_default=default,
        external_ref=ext, created_at=T0 + timedelta(minutes=minutes),
    )
    db.add(ws)
    db.flush()
    return ws.id


def _new_app(session_factory, name, tenant_id=DEFAULT_TENANT_ID):
    db = session_factory()
    app = _service(db).find_or_create_by_name(tenant_id, name, created_by="test")
    db.commit()
    app_id = app.id
    db.close()
    return app_id


def _key_for(client, app_id=None, name="Key", headers=None):
    body = {"name": name}
    if app_id is not None:
        body["clientAppId"] = app_id
    res = client.post(KEYS, json=body, headers=headers or _auth(client))
    assert res.status_code == 201, res.text
    return res.json(), {"Authorization": f"Bearer {res.json()['fullKey']}"}


def _put(client, hdr, ext, name="Org"):
    return client.put(f"{P}/workspaces/{ext}", json={"name": name}, headers=hdr)


# ── backfill rule ────────────────────────────────────────────────────────────
def test_one_client_app_per_workspace_name_grouping_namesakes(session_factory):
    """The live-data shape: several apps in one tenant, namesakes grouped."""
    m = _models()
    tid = "ca-multi-tenant"
    db = session_factory()
    ids = {
        "ecohub_trashed": _ws(db, tid, "ecohub ", 1, trashed=True),  # older, trashed
        "ecohub": _ws(db, tid, "Ecohub", 2, default=True),
        "sorento": _ws(db, tid, "Sorento", 3),
        "sorento_trashed": _ws(db, tid, "SORENTO", 4, trashed=True),
        "myfuji": _ws(db, tid, "MyFuji Platform", 5),
        "test": _ws(db, tid, "Test", 6, trashed=True),
        "foundryx": _ws(db, tid, "Foundryx", 7, trashed=True),
    }
    db.add(m.PartnerApiKey(tenant_id=tid, name="k", key_prefix="mmmmmmmm", key_hash="0" * 64))
    db.commit()

    _service(db).backfill_tenant(tid)
    db.commit()
    apps = _apps(db, tid)
    assert sorted(a.name for a in apps) == ["Ecohub", "Foundryx", "MyFuji Platform", "Sorento", "Test"]
    assert all(a.created_by == "backfill" and a.status == "ACTIVE" and a.slug is None for a in apps)
    assert _app_of(db, ids["ecohub"]).id == _app_of(db, ids["ecohub_trashed"]).id
    assert _app_of(db, ids["ecohub"]).name == "Ecohub"  # the live one names it
    assert _app_of(db, ids["sorento"]).id == _app_of(db, ids["sorento_trashed"]).id
    assert _app_of(db, ids["test"]).name == "Test"  # trashed, no live namesake: its own app
    (default,) = [a for a in apps if a.is_default]
    assert default.id == _app_of(db, ids["ecohub"]).id  # the default workspace's app
    assert db.query(m.PartnerApiKey).filter_by(tenant_id=tid).one().client_app_id == default.id

    # Idempotent: nothing new on a re-run, nothing moved.
    before = {w.id: w.client_app_id for w in db.query(m.Workspace).filter_by(tenant_id=tid)}
    _service(db).backfill_tenant(tid)
    db.commit()
    assert len(_apps(db, tid)) == 5
    assert {w.id: w.client_app_id for w in db.query(m.Workspace).filter_by(tenant_id=tid)} == before
    db.close()


def test_without_a_default_workspace_the_oldest_client_app_is_default(session_factory):
    tid = "ca-no-default"
    db = session_factory()
    _ws(db, tid, "Beta", 2)
    alpha = _ws(db, tid, "Alpha", 1)
    db.commit()
    _service(db).backfill_tenant(tid)
    db.commit()
    (default,) = [a for a in _apps(db, tid) if a.is_default]
    assert default.id == _app_of(db, alpha).id
    db.close()


def test_a_tenant_with_only_general_gets_one_default_general_app(client, session_factory):
    m = _models()
    tid, _ = other_tenant(client, session_factory, slug="ca-general")
    db = session_factory()
    (app,) = _apps(db, tid)
    assert app.name == "General" and app.is_default and app.created_by == "install"
    general = db.query(m.Workspace).filter_by(tenant_id=tid, is_default=True).one()
    assert general.client_app_id == app.id
    # The backfill of a stripped copy reaches the same shape.
    _strip_parents(db, tid)
    _service(db).backfill_tenant(tid)
    db.commit()
    (again,) = _apps(db, tid)
    assert again.name == "General" and again.is_default
    db.close()


def test_backfill_leaves_other_tenants_untouched(client, session_factory):
    m = _models()
    other_id, _ = other_tenant(client, session_factory, slug="ca-other")
    db = session_factory()
    _strip_parents(db, other_id)
    _strip_parents(db, DEFAULT_TENANT_ID)
    _service(db).backfill_tenant(DEFAULT_TENANT_ID)
    db.commit()
    assert _apps(db, other_id) == []
    other_rows = db.query(m.Workspace).filter(m.Workspace.tenant_id == other_id).all()
    assert other_rows and all(w.client_app_id is None for w in other_rows)
    db.close()


def test_install_already_installed_branch_runs_the_backfill(session_factory):
    from modules.omnichannel.bootstrap import install_tenant

    m = _models()
    db = session_factory()
    _ws(db, DEFAULT_TENANT_ID, "Sales", 1)
    db.commit()
    _strip_parents(db, DEFAULT_TENANT_ID)
    install_tenant(db, DEFAULT_TENANT_ID)
    db.commit()
    rows = db.query(m.Workspace).filter(m.Workspace.tenant_id == DEFAULT_TENANT_ID).all()
    assert all(w.client_app_id for w in rows)
    assert {a.name for a in _apps(db, DEFAULT_TENANT_ID)} == {w.name for w in rows}
    db.close()


def test_a_partner_made_workspace_and_keys_join_the_default_app(client, session_factory):
    """Rows from the partner route (external_ref) follow the keys, not their name."""
    m = _models()
    partner_headers(client)
    db = session_factory()
    org = _ws(db, DEFAULT_TENANT_ID, "Acme Sdn Bhd", 1, ext="org-acme")
    db.commit()
    _strip_parents(db, DEFAULT_TENANT_ID)
    _service(db).backfill_tenant(DEFAULT_TENANT_ID)
    db.commit()
    default = db.query(m.ClientApp).filter_by(tenant_id=DEFAULT_TENANT_ID, is_default=True).one()
    assert default.name == "General"
    assert _app_of(db, org).id == default.id
    assert {k.client_app_id for k in db.query(m.PartnerApiKey).all()} == {default.id}
    assert "Acme Sdn Bhd" not in {a.name for a in _apps(db, DEFAULT_TENANT_ID)}
    db.close()


# ── new workspaces ───────────────────────────────────────────────────────────
def test_dashboard_create_gets_the_client_app_named_after_it(client, session_factory):
    h = _auth(client)
    first = client.post("/omnichannel/workspaces", json={"name": "Brand New"}, headers=h)
    again = client.post("/omnichannel/workspaces", json={"name": "  brand new "}, headers=h)
    general = client.post("/omnichannel/workspaces", json={"name": "general"}, headers=h)
    assert first.status_code in (200, 201) and again.status_code in (200, 201), first.text
    db = session_factory()
    app = _app_of(db, first.json()["id"])
    assert app.name == "Brand New" and not app.is_default and app.created_by == "dashboard"
    assert _app_of(db, again.json()["id"]).id == app.id  # same normalised name: reused
    assert _app_of(db, general.json()["id"]).is_default  # joins the existing "General" app
    assert len([a for a in _apps(db, DEFAULT_TENANT_ID) if a.is_default]) == 1
    db.close()


def test_partner_create_and_key_mint_use_the_keys_client_app(client, session_factory):
    m = _models()
    hdr = partner_headers(client)  # no clientAppId: the tenant default
    wid = _put(client, hdr, "org-parent", name="Some Org").json()["id"]
    db = session_factory()
    default = db.query(m.ClientApp).filter_by(tenant_id=DEFAULT_TENANT_ID, is_default=True).one()
    assert _app_of(db, wid).id == default.id
    assert {k.client_app_id for k in db.query(m.PartnerApiKey).all()} == {default.id}
    db.close()


# ── NULL parent from an older running version ────────────────────────────────
def test_a_null_parent_workspace_is_resolved_by_name_and_persisted(client, session_factory):
    m = _models()
    hdr = partner_headers(client)
    db = session_factory()
    sorento = _ws(db, DEFAULT_TENANT_ID, "Sorento", 1)  # what an older version writes
    general_twin = _ws(db, DEFAULT_TENANT_ID, " GENERAL", 2)
    db.commit()
    db.close()
    assert client.get(f"{P}/me", headers=hdr).status_code == 200  # any partner call heals
    db = session_factory()
    assert _app_of(db, sorento).name == "Sorento" and not _app_of(db, sorento).is_default
    assert _app_of(db, general_twin).is_default
    db.close()
    # The dashboard list heals too.
    db = session_factory()
    later = _ws(db, DEFAULT_TENANT_ID, "Later", 3)
    db.commit()
    db.close()
    assert client.get(APPS, headers=_auth(client)).status_code == 200
    db = session_factory()
    assert _app_of(db, later).name == "Later"
    assert db.query(m.Workspace).filter_by(client_app_id=None).count() == 0
    db.close()


def test_a_null_parent_partner_key_falls_back_to_the_default(client, session_factory):
    m = _models()
    hdr = partner_headers(client)
    db = session_factory()
    db.query(m.PartnerApiKey).update({"client_app_id": None})
    db.commit()
    db.close()
    me = client.get(f"{P}/me", headers=hdr)
    assert me.status_code == 200, me.text
    db = session_factory()
    default = db.query(m.ClientApp).filter_by(tenant_id=DEFAULT_TENANT_ID, is_default=True).one()
    assert me.json()["clientAppId"] == default.id and me.json()["clientAppName"] == default.name
    assert db.query(m.PartnerApiKey).one().client_app_id == default.id  # persisted
    db.close()


def test_a_key_only_tenant_gets_a_default_app_named_after_the_tenant(session_factory):
    m = _models()
    db = session_factory()
    db.add(m.PartnerApiKey(tenant_id="key-only", name="k", key_prefix="abcdefgh", key_hash="0" * 64))
    db.commit()
    app = _service(db).default_for_tenant("key-only")
    db.commit()
    assert app.is_default and app.name == "Default"  # no tenant row to name it after
    db.close()


# ── partner key mint with a client app, and the read-only list ──────────────
def test_mint_accepts_an_optional_client_app_of_the_callers_tenant(client, session_factory):
    eco = _new_app(session_factory, "Ecohub")
    body, hdr = _key_for(client, eco, name="EcoHub")
    assert body["key"]["clientAppId"] == eco and body["key"]["clientAppName"] == "Ecohub"
    assert client.get(f"{P}/me", headers=hdr).json()["clientAppId"] == eco
    plain, _ = _key_for(client, None, name="Plain")  # the existing body still works
    db = session_factory()
    default = _service(db).repo.get_default(DEFAULT_TENANT_ID)
    db.close()
    assert plain["key"]["clientAppId"] == default.id
    listed = client.get(KEYS, headers=_auth(client)).json()["data"]
    assert {k["name"]: k["clientAppName"] for k in listed} == {"EcoHub": "Ecohub", "Plain": default.name}

    other_id, admin_b = other_tenant(client, session_factory, slug="ca-mint-b")
    db = session_factory()
    foreign = _apps(db, other_id)[0].id
    db.close()
    for bad in (foreign, "00000000-0000-0000-0000-00000000dead"):
        res = client.post(KEYS, json={"name": "x", "clientAppId": bad}, headers=_auth(client))
        assert res.status_code == 422, res.text
    assert client.post(KEYS, json={"name": "x", "clientAppId": eco}, headers=admin_b).status_code == 422


def test_client_app_list_is_read_only_scoped_and_permissioned(client, session_factory):
    eco = _new_app(session_factory, "Ecohub")
    hdr = partner_headers(client)
    _put(client, hdr, "org-count", name="Org")  # default app gains a live workspace
    other_tenant(client, session_factory, slug="ca-list-b")
    res = client.get(APPS, headers=_auth(client))
    assert res.status_code == 200, res.text
    items = {a["name"]: a for a in res.json()["data"]}
    assert set(items) == {"General", "Ecohub"}  # never another tenant's
    assert set(items["General"]) == {"id", "name", "slug", "status", "isDefault", "workspaceCount"}
    assert items["General"]["isDefault"] is True and items["General"]["workspaceCount"] == 2
    assert items["Ecohub"] == {
        "id": eco, "name": "Ecohub", "slug": None, "status": "ACTIVE", "isDefault": False,
        "workspaceCount": 0,
    }
    assert client.get(APPS, headers=_no_perm_auth(client, session_factory, "ca-noperm@example.com")).status_code == 403
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert client.request(method, APPS, headers=_auth(client), json={}).status_code == 405


# ── partner routes scoped by client app ──────────────────────────────────────
ID_ROUTES = [
    ("GET", "/workspaces/{ws}", None),
    ("GET", "/workspaces/{ws}/channels", None),
    ("GET", "/workspaces/{ws}/api-keys", None),
    ("POST", "/workspaces/{ws}/api-keys", {"name": "iso"}),
    ("POST", "/workspaces/{ws}/api-keys/any-key-id/revoke", None),
]


@pytest.mark.parametrize("method,path,body", ID_ROUTES)
def test_two_client_apps_in_one_tenant_are_isolated(client, session_factory, method, path, body):
    _, hdr_eco = _key_for(client, _new_app(session_factory, "Ecohub"), name="EcoHub")
    _, hdr_fuji = _key_for(client, _new_app(session_factory, "MyFuji Platform"), name="Fuji")
    ws_eco = _put(client, hdr_eco, "org-1").json()["id"]
    ws_fuji = _put(client, hdr_fuji, "org-2").json()["id"]
    _seed_channel(session_factory, ws_eco, phone_number_id="pn-ca-eco")
    for own_hdr, own_ws, other_hdr in ((hdr_eco, ws_eco, hdr_fuji), (hdr_fuji, ws_fuji, hdr_eco)):
        url = P + path.format(ws=own_ws)
        own = client.request(method, url, headers=own_hdr, json=body)
        assert own.status_code != 404 or own.json() != NOT_FOUND, own.text  # control
        cross = client.request(method, url, headers=other_hdr, json=body)
        assert cross.status_code == 404 and cross.json() == NOT_FOUND
    # The default "General" belongs to neither.
    general = _default_workspace_id(session_factory)
    assert client.get(f"{P}/workspaces/{general}", headers=hdr_eco).json() == NOT_FOUND


def test_list_shows_only_the_keys_client_app_and_external_ref_repeats_across_apps(client, session_factory):
    eco_app = _new_app(session_factory, "Ecohub")
    _, hdr_eco = _key_for(client, eco_app, name="EcoHub")
    _, hdr_fuji = _key_for(client, _new_app(session_factory, "MyFuji Platform"), name="Fuji")
    eco = _put(client, hdr_eco, "org-42", name="Eco 42").json()
    fuji = _put(client, hdr_fuji, "org-42", name="Fuji 42")
    assert fuji.status_code == 200, fuji.text
    assert fuji.json()["id"] != eco["id"]  # same externalOrgId, two client apps, one tenant
    for hdr, mine in ((hdr_eco, eco["id"]), (hdr_fuji, fuji.json()["id"])):
        listed = client.get(f"{P}/workspaces", params={"pageSize": 100}, headers=hdr).json()
        assert [w["id"] for w in listed["data"]] == [mine] and listed["total"] == 1
        one = client.get(f"{P}/workspaces", params={"externalOrgId": "org-42"}, headers=hdr).json()
        assert [w["id"] for w in one["data"]] == [mine]
    assert _put(client, hdr_eco, "org-42", name="Eco 42").json()["id"] == eco["id"]  # idempotent per app
    db = session_factory()
    assert _app_of(db, eco["id"]).id == eco_app
    db.close()


def test_moving_a_workspace_moves_partner_access_and_keeps_its_workspace_keys(client, session_factory):
    """The later manual split: re-pointing a workspace is all it takes."""
    m = _models()
    _, hdr_first = _key_for(client, None, name="First")
    wid = _put(client, hdr_first, "org-move").json()["id"]
    _seed_channel(session_factory, wid, phone_number_id="pn-ca-move")
    workspace_key = client.post(
        f"{P}/workspaces/{wid}/api-keys", json={"name": "org key"}, headers=hdr_first
    ).json()["fullKey"]
    app2 = _new_app(session_factory, "Second app")
    _, hdr_second = _key_for(client, app2, name="Second")
    db = session_factory()
    db.query(m.Workspace).filter(m.Workspace.id == wid).update({"client_app_id": app2})
    db.commit()
    db.close()
    assert client.get(f"{P}/workspaces/{wid}", headers=hdr_second).status_code == 200
    assert client.get(f"{P}/workspaces/{wid}", headers=hdr_first).json() == NOT_FOUND
    pub = client.get("/api/v1/omnichannel/templates", headers={"Authorization": f"Bearer {workspace_key}"})
    assert pub.status_code == 200, pub.text


# ── DISABLED blocks partner routes only ──────────────────────────────────────
def test_a_disabled_client_app_blocks_partner_routes_but_not_workspace_keys(client, session_factory):
    m = _models()
    hdr = partner_headers(client)
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-ca-disabled")
    workspace_key = _mint(client, ws).json()["fullKey"]
    db = session_factory()
    db.query(m.ClientApp).filter_by(tenant_id=DEFAULT_TENANT_ID).update({"status": "DISABLED"})
    db.commit()
    db.close()

    for method, path in (("GET", "/me"), ("GET", "/workspaces"), ("PUT", "/workspaces/org-d")):
        res = client.request(method, P + path, headers=hdr, json={"name": "x"} if method == "PUT" else None)
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "client_app_disabled"
    # The tenant's workspace key, the dashboard and webhooks never look at it.
    pub = client.get("/api/v1/omnichannel/templates", headers={"Authorization": f"Bearer {workspace_key}"})
    assert pub.status_code == 200, pub.text
    assert client.get("/omnichannel/workspaces", headers=_auth(client)).status_code == 200
    assert client.get(KEYS, headers=_auth(client)).status_code == 200


# ── uninstall ────────────────────────────────────────────────────────────────
def test_uninstall_deletes_client_apps_after_their_children_and_keeps_other_tenants(client, session_factory):
    from app.services.app_store_service import AppStoreService

    m = _models()
    tables = [t.name for t in m.OmniBase.metadata.sorted_tables]
    # The cleanup loop runs in reverse: children first, then client_apps.
    assert tables.index("client_apps") < tables.index("workspaces")
    assert tables.index("client_apps") < tables.index("partner_api_keys")

    tid, admin = other_tenant(client, session_factory, slug="ca-uninstall")
    partner_headers(client, admin, name="Other")
    db = session_factory()
    assert _apps(db, tid)
    AppStoreService(db).uninstall(tid, "omnichannel", "omnichannel")
    db.commit()
    assert _apps(db, tid) == []
    assert db.query(m.Workspace).filter_by(tenant_id=tid).count() == 0
    assert db.query(m.PartnerApiKey).filter_by(tenant_id=tid).count() == 0
    assert _apps(db, DEFAULT_TENANT_ID)
    db.close()


# ── schema: model, Alembic and the bootstrap mirror agree ────────────────────
def test_client_app_migration_revises_the_omnichannel_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(VERSIONS.parent))
    assert script.get_heads() == ["0032_omni_client_apps"]
    rev = script.get_revision("0032_omni_client_apps")
    assert rev.down_revision == "0031_omni_workspace_external_ref"
    assert len(rev.revision) <= 32


def _migration_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("omni_0032", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _upgrade_sql(monkeypatch):
    mod = _migration_module()
    seen = []
    monkeypatch.setattr(mod.op, "execute", lambda sql: seen.append(_norm(str(sql))), raising=False)
    mod.upgrade()
    return mod, seen


def _bootstrap_sql(monkeypatch):
    """Every statement `create_schema_and_tables` runs on Postgres."""
    from modules.omnichannel import bootstrap

    seen = []

    class _Result:
        def fetchall(self):
            return []

        def __iter__(self):
            return iter(())

    class _Conn:
        def execute(self, stmt, *a, **k):
            seen.append(_norm(str(stmt)))
            return _Result()

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *exc):
            return False

    class _Engine:
        class dialect:
            name = "postgresql"

        def begin(self):
            return _Begin()

    monkeypatch.setattr(bootstrap.OmniBase.metadata, "create_all", lambda **k: None)
    bootstrap.create_schema_and_tables(_Engine())
    return seen


def test_the_bootstrap_mirror_runs_the_migration_statements_verbatim(monkeypatch):
    mod, upgrade = _upgrade_sql(monkeypatch)
    mirror = _bootstrap_sql(monkeypatch)
    mirrored = [_norm(s) for s in mod.MIRRORED]
    assert upgrade == [_norm(mod.CREATE_TABLE)] + [_norm(s) for s in mod.TABLE_INDEXES] + mirrored
    start = mirror.index(mirrored[0])
    assert mirror[start : start + len(mirrored)] == mirrored
    # The per-tenant index is never created again; the per-client-app one is.
    assert not any("CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_tenant_external_ref" in s for s in mirror)


def test_the_parents_stay_nullable_and_external_ref_is_unique_per_client_app():
    m = _models()
    assert m.Workspace.__table__.c.client_app_id.nullable
    assert m.PartnerApiKey.__table__.c.client_app_id.nullable
    ext = [i for i in m.Workspace.__table__.indexes if i.name == "uq_workspaces_client_app_external_ref"]
    assert ext and ext[0].unique and [c.name for c in ext[0].columns] == ["client_app_id", "external_ref"]
    assert not any("hash" in c.name or "secret" in c.name for c in m.ClientApp.__table__.columns)
