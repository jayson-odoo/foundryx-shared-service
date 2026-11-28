"""AI dashboard builder S1 (SS) red tests: key auth, tenant + product isolation, staff key issue (S-16b, F5-F7).

Every gateway endpoint is exercised for every rule: default deny, then the key's tenant + product are the only
scope a caller can ever see.
"""
from __future__ import annotations

import pytest

from app.ai.stub import stub_fixtures
from app.models import DEFAULT_TENANT_ID
from tests.dashboards_helpers import dash, dstaff  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import (
    BASE,
    OTHER,
    OWNER,
    VIEWER,
    add_op,
    assert_flat_error,
    create_dash,
    empty_draft,
    f1_spec,
    f1_tiles,
    get,
    hdr,
    issue_key,
    listing,
    ops_out,
    save,
    share,
    turn,
    versions,
)
from tests.dashboards_helpers import CATALOGUE, new_idem
from tests.planner3d_helpers import err_code, login, make_user_with  # noqa: F401
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: F401
from tests.meetings_helpers import make_tenant


# -- one callable per endpoint ---------------------------------------------------------------------

def calls(client, key, did, *, body_extra=None, query_extra=None, actor=OWNER):
    """name -> zero-arg callable returning the response. Valid payloads, so only auth/echo rules can refuse."""
    be = dict(body_extra or {})
    qe = dict(query_extra or {})
    h = hdr(key)

    def post(path, body):
        return lambda: client.post(f"{BASE}{path}", json={**body, **be}, headers=h)

    def getter(path):
        return lambda: client.get(f"{BASE}{path}", params={"actor_ref": actor, **qe}, headers=h)

    return {
        "turn": post("/builder/turn", {"actor_ref": actor, "dashboard_id": None, "draft": empty_draft(),
                                       "message": "sales by month", "catalogue": CATALOGUE, "refusals": [], "history": []}),
        "list": getter(""),
        "get": getter(f"/{did}"),
        "versions": getter(f"/{did}/versions"),
        "save": post("/save", {"actor_ref": actor, "dashboard_id": None, "name": "Another", "spec": f1_spec(),
                               "base_version": None, "idempotency_key": new_idem()}),
        "share": post(f"/{did}/share", {"actor_ref": actor, "shared_with": [{"user_ref": VIEWER}]}),
        "delete": post(f"/{did}/delete", {"actor_ref": actor}),
    }


ENDPOINTS = ["turn", "list", "get", "versions", "save", "share", "delete"]


# -- F5: no / bad / revoked key --------------------------------------------------------------------

@pytest.mark.parametrize("name", ENDPOINTS)
def test_no_key_is_401_invalid_api_key(client, dash, name):
    d = create_dash(client, dash.sorento)
    assert_flat_error(calls(client, None, d["id"])[name](), 401, "invalid_api_key")


@pytest.mark.parametrize("name", ENDPOINTS)
def test_unknown_key_is_401_invalid_api_key(client, dash, name):
    d = create_dash(client, dash.sorento)
    assert_flat_error(calls(client, "bad-key", d["id"])[name](), 401, "invalid_api_key")
    assert_flat_error(calls(client, "fxd_live_" + "0" * 40, d["id"])[name](), 401, "invalid_api_key")


@pytest.mark.parametrize("name", ENDPOINTS)
def test_revoked_key_is_401_invalid_api_key(client, dash, name):
    from modules.dashboards.services import key_service

    d = create_dash(client, dash.sorento)
    db = dash.sf()
    try:
        key_service.revoke(db, DEFAULT_TENANT_ID, dash.key_ids["sorento"])
        db.commit()
    finally:
        db.close()
    assert_flat_error(calls(client, dash.sorento, d["id"])[name](), 401, "invalid_api_key")
    # the other keys are untouched
    assert listing(client, dash.ecohub, OWNER).status_code == 200


def test_a_bearer_staff_token_is_not_a_gateway_key(client, dash, dstaff):
    res = client.get(BASE, params={"actor_ref": OWNER}, headers=dstaff)
    assert_flat_error(res, 401, "invalid_api_key")


# -- F6: module off --------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ENDPOINTS)
def test_module_deactivated_for_the_tenant_is_403_service_not_enabled(client, dash, name):
    from app.services.app_store_service import AppStoreService

    d = create_dash(client, dash.sorento)
    db = dash.sf()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "dashboards")
        db.commit()
    finally:
        db.close()
    assert_flat_error(calls(client, dash.sorento, d["id"])[name](), 403, "service_not_enabled")
    # tenant B still has it
    assert listing(client, dash.b_sorento, OWNER).status_code == 200


def test_reactivating_restores_access_and_data(client, dash):
    from app.services.app_store_service import AppStoreService

    d = create_dash(client, dash.sorento)
    db = dash.sf()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "dashboards")
        db.commit()
        AppStoreService(db).reactivate(DEFAULT_TENANT_ID, "dashboards")
        db.commit()
    finally:
        db.close()
    assert get(client, dash.sorento, OWNER, d["id"]).status_code == 200


# -- tenant and product walls ----------------------------------------------------------------------

@pytest.fixture
def foreign(client, dash):
    """A dashboard in tenant B (sorento), one in tenant A under ecohub, both owned by the SAME actor ref."""
    return {"b": create_dash(client, dash.b_sorento, OWNER, "B sales")["id"],
            "eco": create_dash(client, dash.ecohub, OWNER, "Eco sales")["id"]}


@pytest.mark.parametrize("which", ["b", "eco"])
@pytest.mark.parametrize("name", ["get", "versions", "save", "share", "delete", "turn"])
def test_other_tenant_or_product_dashboard_is_404_not_403(client, dash, foreign, which, name):
    did = foreign[which]
    h = hdr(dash.sorento)
    if name == "get":
        res = get(client, dash.sorento, OWNER, did)
    elif name == "versions":
        res = versions(client, dash.sorento, OWNER, did)
    elif name == "save":
        res = save(client, dash.sorento, OWNER, "Hijack", f1_spec(), dashboard_id=did, base_version=1)
    elif name == "share":
        res = share(client, dash.sorento, OWNER, did, [VIEWER])
    elif name == "delete":
        res = client.post(f"{BASE}/{did}/delete", json={"actor_ref": OWNER}, headers=h)
    else:
        res = turn(client, dash.sorento, OWNER, "x", dashboard_id=did)
    assert_flat_error(res, 404, "not_found")


@pytest.mark.parametrize("which", ["b", "eco"])
def test_other_tenant_or_product_dashboard_is_never_listed_and_survives(client, dash, foreign, which):
    mine = create_dash(client, dash.sorento, OWNER, "My own")["id"]
    for scope in ("all", "mine", "shared"):
        ids = [i["id"] for i in listing(client, dash.sorento, OWNER, scope=scope).json()["items"]]
        assert foreign[which] not in ids
    assert [i["id"] for i in listing(client, dash.sorento, OWNER).json()["items"]] == [mine]
    # still intact for its own key
    own_key = {"b": dash.b_sorento, "eco": dash.ecohub}[which]
    assert get(client, own_key, OWNER, foreign[which]).json()["version"] == 1
    assert [i["name"] for i in listing(client, own_key, OWNER).json()["items"]] == [{"b": "B sales", "eco": "Eco sales"}[which]]


def test_share_cannot_cross_into_another_product(client, dash, foreign):
    mine = create_dash(client, dash.sorento, OWNER, "My own")["id"]
    assert share(client, dash.sorento, OWNER, mine, [OTHER]).status_code == 200
    # an ecohub caller with the same user ref still cannot see it
    assert listing(client, dash.ecohub, OTHER).json()["items"] == []
    assert get(client, dash.ecohub, OTHER, mine).status_code == 404


# -- F7: echoed tenant / product -------------------------------------------------------------------

def _mismatch_calls(client, dash, did, **kw):
    return calls(client, dash.sorento, did, **kw)


@pytest.mark.parametrize("name", ENDPOINTS)
def test_product_mismatch_on_every_endpoint(client, dash, name):
    d = create_dash(client, dash.sorento)
    body_c = calls(client, dash.sorento, d["id"], body_extra={"product": "ecohub"}, query_extra={"product": "ecohub"})
    assert_flat_error(body_c[name](), 403, "product_mismatch")


@pytest.mark.parametrize("ref", ["id", "slug"])
@pytest.mark.parametrize("name", ENDPOINTS)
def test_tenant_mismatch_on_every_endpoint(client, dash, name, ref):
    d = create_dash(client, dash.sorento)
    wrong = dash.tenant_b if ref == "id" else dash.tenant_b_slug
    c = calls(client, dash.sorento, d["id"], body_extra={"tenant": wrong}, query_extra={"tenant": wrong})
    assert_flat_error(c[name](), 403, "tenant_mismatch")


def test_a_mismatch_changes_nothing(client, dash):
    d = create_dash(client, dash.sorento)
    c = calls(client, dash.sorento, d["id"], body_extra={"product": "ecohub"}, query_extra={"product": "ecohub"})
    assert c["share"]().status_code == 403 and c["delete"]().status_code == 403 and c["save"]().status_code == 403
    assert get(client, dash.sorento, OWNER, d["id"]).json()["shared_with"] == []
    assert listing(client, dash.sorento, OWNER).json()["total"] == 1


def test_matching_tenant_id_slug_and_product_are_accepted_everywhere(client, dash):
    d = create_dash(client, dash.sorento)
    d2 = create_dash(client, dash.sorento, OWNER, "To delete")
    for tenant in (dash.tenant_a, dash.tenant_a_slug):
        for name in ("turn", "list", "get", "versions", "save", "share"):
            with stub_fixtures(ops_out("ok", add_op(f1_tiles()[0]))):
                c = calls(client, dash.sorento, d["id"], body_extra={"tenant": tenant, "product": "sorento_crm"},
                          query_extra={"tenant": tenant, "product": "sorento_crm"})
                res = c[name]()
            assert res.status_code == 200, (tenant, name, res.text)
    c = calls(client, dash.sorento, d2["id"], body_extra={"tenant": dash.tenant_a_slug, "product": "sorento_crm"})
    assert c["delete"]().status_code == 200


# -- staff issues keys -----------------------------------------------------------------------------

def test_staff_issues_a_key_that_works_on_the_gateway(client, dash, dstaff):
    res = client.post("/dashboards-admin/keys", json={"name": "CRM", "product": "sorento_crm"}, headers=dstaff)
    assert res.status_code == 201, res.text
    body = res.json()
    assert {"id", "key", "product", "masked"} <= set(body)
    assert body["key"].startswith("fxd_live_") and body["product"] == "sorento_crm"
    assert body["masked"] != body["key"] and body["key"] not in body["masked"]
    ok = listing(client, body["key"], OWNER)
    assert ok.status_code == 200
    # a key issued for ecohub is bound to ecohub: it cannot echo the sorento product
    eco = client.post("/dashboards-admin/keys", json={"name": "Hub", "product": "ecohub"}, headers=dstaff).json()
    assert_flat_error(client.get(BASE, params={"actor_ref": OWNER, "product": "sorento_crm"}, headers=hdr(eco["key"])),
                      403, "product_mismatch")


def test_staff_unknown_product_is_422(client, dash, dstaff):
    res = client.post("/dashboards-admin/keys", json={"name": "CRM", "product": "nonsense"}, headers=dstaff)
    assert res.status_code == 422, res.text
    assert client.post("/dashboards-admin/keys", json={"name": "CRM"}, headers=dstaff).status_code == 422


def test_staff_without_the_permission_is_403_and_anonymous_is_401(client, dash):
    db = dash.sf()
    try:
        make_user_with(db, DEFAULT_TENANT_ID, "dash-none@example.com", [], "Dash Nothing")
        db.commit()
    finally:
        db.close()
    nobody = login(client, "dash-none@example.com")
    res = client.post("/dashboards-admin/keys", json={"name": "CRM", "product": "sorento_crm"}, headers=nobody)
    assert res.status_code == 403, res.text
    assert client.post("/dashboards-admin/keys", json={"name": "CRM", "product": "sorento_crm"}).status_code == 401


def test_staff_key_is_scoped_to_the_staff_tenant(client, dash, dstaff):
    body = client.post("/dashboards-admin/keys", json={"name": "CRM", "product": "sorento_crm"}, headers=dstaff).json()
    create_dash(client, body["key"], OWNER, "Mine")
    # tenant B's key sees nothing of it
    assert listing(client, dash.b_sorento, OWNER).json()["items"] == []
