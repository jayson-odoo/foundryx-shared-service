"""BR Send to build - S3: build write-back keys + the public events endpoint +
status close (AC-STB-15, 16, 17, 18, 22).

RED until ``BuildKeyService``, ``/ideation/build-keys`` and the public
``POST /ideation/build/{brId}/events`` land. Sent BRs are seeded by direct rows
(``insert_sent_br``) so nothing here depends on the Send endpoint.
"""
import re

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.ideation_build_helpers import (  # noqa: F401
    OTHER_TENANT_ID,
    _auth,
    _product,
    bearer,
    br_status_key,
    ensure_other_tenant,
    ideation_client,
    insert_key_row,
    insert_sent_br,
    make_br,
    mint_key_via_api,
)

GOOD = {"stage": "PR+CI", "message": "Draft PR opened"}


def _post(client, br_id, key, body=None, headers=None):
    hdr = bearer(key) if key is not None else {}
    if headers is not None:
        hdr = headers
    return client.post(
        f"/ideation/build/{br_id}/events", headers=hdr, json=GOOD if body is None else body
    )


def _sent(client, h):
    """(product id, sent BR id, plaintext key) for the default tenant."""
    pid = _product(client, h)
    br_id = insert_sent_br(client._factory, product_id=pid)
    key = mint_key_via_api(client, h)
    return pid, br_id, key["plaintext"]


def _event_rows(factory, br_id):
    from modules.ideation.models import BrBuildEvent

    db = factory()
    try:
        return [
            (e.kind, e.stage, e.status, e.status_moved, e.key_id, e.actor_user_id)
            for e in db.query(BrBuildEvent)
            .filter(BrBuildEvent.business_requirement_id == br_id)
            .order_by(BrBuildEvent.seq)
        ]
    finally:
        db.close()


# ── AC-STB-15 keys ───────────────────────────────────────────────────────────


def test_ac_stb_15_mint_returns_plaintext_once_with_scheme(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.post("/ideation/build-keys", headers=h, json={"name": "crew"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert re.fullmatch(r"fxb_live_[A-Za-z0-9_-]{32}", body["plaintext"]), body["plaintext"]
    assert body["name"] == "crew"
    assert body["keyPrefix"] == body["plaintext"][9:17]
    assert body["id"]


def test_ac_stb_15_only_hash_and_prefix_are_stored(ideation_client, ideation_session_factory):
    import hashlib

    from modules.ideation.models import BrBuildKey

    h = _auth(ideation_client)
    key = mint_key_via_api(ideation_client, h)
    db = ideation_session_factory()
    try:
        row = db.get(BrBuildKey, key["id"])
        assert row.tenant_id == DEFAULT_TENANT_ID
        assert row.key_hash == hashlib.sha256(key["plaintext"].encode()).hexdigest()
        assert row.key_prefix == key["plaintext"][9:17]
        for col in row.__table__.c:
            value = getattr(row, col.name)
            assert key["plaintext"] != value  # plaintext is never persisted
        assert row.last_used_at is None and row.revoked_at is None
    finally:
        db.close()


def test_ac_stb_15_mint_requires_a_name(ideation_client):
    h = _auth(ideation_client)
    assert ideation_client.post("/ideation/build-keys", headers=h, json={}).status_code == 422


def test_ac_stb_15_list_shows_no_plaintext_and_is_tenant_scoped(
    ideation_client, ideation_session_factory
):
    ensure_other_tenant(ideation_session_factory)
    insert_key_row(ideation_session_factory, OTHER_TENANT_ID)
    h = _auth(ideation_client)
    mine = mint_key_via_api(ideation_client, h, name="mine")
    res = ideation_client.get("/ideation/build-keys", headers=h)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["id"] for r in rows] == [mine["id"]]
    assert rows[0]["name"] == "mine"
    assert rows[0]["keyPrefix"] == mine["keyPrefix"]
    assert "createdAt" in rows[0] and "lastUsedAt" in rows[0]
    assert "plaintext" not in rows[0]
    assert mine["plaintext"] not in res.text


def test_ac_stb_15_revoke_204_and_key_stops_resolving(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    keys = ideation_client.get("/ideation/build-keys", headers=h).json()
    key_id = keys[0]["id"]
    assert _post(ideation_client, br_id, key).status_code == 201  # control: works
    res = ideation_client.delete(f"/ideation/build-keys/{key_id}", headers=h)
    assert res.status_code == 204, res.text
    after = _post(ideation_client, br_id, key)
    assert after.status_code == 401, after.text
    assert after.json()["error"]["code"] == "invalid_api_key"
    # The refused post stored nothing (only the control entry exists).
    assert len(_event_rows(ideation_client._factory, br_id)) == 2  # sent + control


def test_ac_stb_15_revoke_other_tenants_or_unknown_key_404(
    ideation_client, ideation_session_factory
):
    ensure_other_tenant(ideation_session_factory)
    foreign = insert_key_row(ideation_session_factory, OTHER_TENANT_ID)
    h = _auth(ideation_client)
    assert ideation_client.delete(f"/ideation/build-keys/{foreign['id']}", headers=h).status_code == 404
    assert ideation_client.delete("/ideation/build-keys/nope", headers=h).status_code == 404
    # The foreign key is untouched: still resolves.
    from modules.ideation.models import BrBuildKey

    db = ideation_session_factory()
    try:
        assert db.get(BrBuildKey, foreign["id"]).revoked_at is None
    finally:
        db.close()


def test_ac_stb_15_service_resolve(ideation_client, ideation_session_factory):
    from modules.ideation.services.build_keys import BuildKeyService

    live = insert_key_row(ideation_session_factory, DEFAULT_TENANT_ID)
    dead = insert_key_row(ideation_session_factory, DEFAULT_TENANT_ID, revoked=True)
    db = ideation_session_factory()
    try:
        svc = BuildKeyService(db)
        row = svc.resolve(live["plaintext"])
        assert row is not None and row.id == live["id"] and row.tenant_id == DEFAULT_TENANT_ID
        assert svc.resolve(dead["plaintext"]) is None
        assert svc.resolve("fxb_live_" + "z" * 32) is None
        assert svc.resolve("fxw_live_" + "z" * 32) is None
        assert svc.resolve("") is None
        assert svc.resolve(None) is None
    finally:
        db.close()


# ── AC-STB-16 append ─────────────────────────────────────────────────────────


def test_ac_stb_16_happy_path_201_shape_and_row(ideation_client, ideation_session_factory):
    from modules.ideation.models import BrBuildKey

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(
        ideation_client,
        br_id,
        key,
        {
            "stage": "PR+CI",
            "message": "Draft PR opened",
            "prUrl": "https://github.com/acme-org/sorento-crm/pull/1410",
            "handtestUrl": "http://localhost:3103",
            "status": "in_progress",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"] and isinstance(body["seq"], int)
    assert body["stage"] == "PR+CI" and body["message"] == "Draft PR opened"
    assert body["prUrl"] == "https://github.com/acme-org/sorento-crm/pull/1410"
    assert body["handtestUrl"] == "http://localhost:3103"
    assert body["status"] == "in_progress"
    assert body["statusMoved"] is False
    assert body["createdAt"].endswith("Z")

    keys = ideation_client.get("/ideation/build-keys", headers=h).json()
    rows = _event_rows(ideation_client._factory, br_id)
    kind, stage, _status, moved, key_id, actor = rows[-1]
    assert (kind, stage, moved, actor) == ("crew", "PR+CI", False, None)
    assert key_id == keys[0]["id"]
    db = ideation_session_factory()
    try:
        assert db.get(BrBuildKey, key_id).last_used_at is not None
    finally:
        db.close()


def test_ac_stb_16_optional_fields_omitted_default_status_in_progress(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, {"stage": "Plan", "message": "Planning."})
    assert res.status_code == 201, res.text
    assert res.json()["prUrl"] is None and res.json()["handtestUrl"] is None
    assert res.json()["status"] == "in_progress"


def test_ac_stb_16_seq_strictly_increases_and_entries_show_on_the_br(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    a = _post(
        ideation_client, br_id, key,
        {"stage": "PR+CI", "message": "one", "prUrl": "https://github.com/a/b/pull/1",
         "handtestUrl": "http://localhost:3103"},
    ).json()
    b = _post(ideation_client, br_id, key, {"stage": "Review", "message": "two"}).json()
    assert b["seq"] > a["seq"]
    build = ideation_client.get(f"/ideation/business-requirements/{br_id}/build", headers=h).json()
    assert [e["stage"] for e in build["events"]] == ["Sent", "PR+CI", "Review"]
    # Summary = latest stage; PR/hand-test = latest NON-empty value.
    assert build["stage"] == "Review"
    assert build["prUrl"] == "https://github.com/a/b/pull/1"
    assert build["handtestUrl"] == "http://localhost:3103"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic Zm9vOmJhcg=="},
        {"Authorization": "Bearer not-a-key"},
        {"Authorization": "Bearer fxb_live_" + "q" * 32},  # right shape, unknown
        {"Authorization": "Bearer fxw_live_" + "q" * 32},  # another module's scheme
        {"X-API-Key": "fxb_live_" + "q" * 32},  # wrong header
    ],
)
def test_ac_stb_16_401_uniform_envelope(ideation_client, headers):
    h = _auth(ideation_client)
    _pid, br_id, _key = _sent(ideation_client, h)
    res = ideation_client.post(f"/ideation/build/{br_id}/events", headers=headers, json=GOOD)
    assert res.status_code == 401, res.text
    assert res.json()["error"]["code"] == "invalid_api_key"
    assert len(_event_rows(ideation_client._factory, br_id)) == 1  # only "sent"


def test_ac_stb_16_a_session_jwt_is_not_a_build_key(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, _key = _sent(ideation_client, h)
    res = ideation_client.post(f"/ideation/build/{br_id}/events", headers=h, json=GOOD)
    assert res.status_code == 401, res.text


def test_ac_stb_16_404_for_other_tenants_br_and_never_sent_br_identical_body(
    ideation_client, ideation_session_factory
):
    ensure_other_tenant(ideation_session_factory)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    key = mint_key_via_api(ideation_client, h)["plaintext"]
    foreign = insert_sent_br(ideation_session_factory, tenant_id=OTHER_TENANT_ID, product_id=pid)
    unsent = make_br(ideation_client, h, pid)  # real BR of this tenant, no build row
    a = _post(ideation_client, foreign, key)
    b = _post(ideation_client, unsent, key)
    c = _post(ideation_client, "does-not-exist", key)
    assert a.status_code == b.status_code == c.status_code == 404
    assert a.json() == b.json() == c.json()
    assert _event_rows(ideation_client._factory, unsent) == []
    assert br_status_key(ideation_client, h, unsent) == "draft"


@pytest.mark.parametrize(
    "body",
    [
        {"stage": "", "message": "m"},
        {"stage": "s", "message": ""},
        {"message": "m"},
        {"stage": "s"},
        {"stage": "s" * 41, "message": "m"},
        {"stage": "s", "message": "m" * 2001},
        {"stage": "s", "message": "m", "prUrl": "javascript:alert(1)"},
        {"stage": "s", "message": "m", "prUrl": "ftp://example.com/x"},
        {"stage": "s", "message": "m", "handtestUrl": "not a url"},
        {"stage": "s", "message": "m", "status": "bogus"},
    ],
)
def test_ac_stb_16_422_on_bad_shape_and_nothing_stored(ideation_client, body):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, body)
    assert res.status_code == 422, (body, res.text)
    assert len(_event_rows(ideation_client._factory, br_id)) == 1


def test_ac_stb_16_length_boundaries_accepted(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, {"stage": "s" * 40, "message": "m" * 2000})
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("status", ["in_progress", "merged", "released", "failed", "cancelled"])
def test_ac_stb_16_every_documented_status_accepted(ideation_client, status):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, {"stage": "x", "message": "y", "status": status})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == status


def test_ac_stb_16_repeated_bad_keys_are_throttled_429(ideation_client):
    """Default policy: 5 bad-key attempts from one client, then 429 + Retry-After
    (the pull-gateway pattern, own ``build`` scope)."""
    h = _auth(ideation_client)
    _pid, br_id, _key = _sent(ideation_client, h)
    bad = bearer("fxb_live_" + "z" * 32)
    for _ in range(5):
        assert ideation_client.post(
            f"/ideation/build/{br_id}/events", headers=bad, json=GOOD
        ).status_code == 401
    res = ideation_client.post(f"/ideation/build/{br_id}/events", headers=bad, json=GOOD)
    assert res.status_code == 429, res.text
    assert res.headers.get("Retry-After")


def test_ac_stb_16_successful_calls_never_consume_the_throttle_bucket(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    for i in range(8):
        assert _post(ideation_client, br_id, key, {"stage": f"s{i}", "message": "m"}).status_code == 201


# ── AC-STB-17 closing the loop ───────────────────────────────────────────────


@pytest.mark.parametrize("status", ["merged", "released"])
def test_ac_stb_17_merged_or_released_moves_the_br_to_delivered(ideation_client, status):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    assert br_status_key(ideation_client, h, br_id) == "sent_to_build"
    res = _post(ideation_client, br_id, key, {"stage": "Merged", "message": "Merged.", "status": status})
    assert res.status_code == 201, res.text
    assert res.json()["statusMoved"] is True
    assert br_status_key(ideation_client, h, br_id) == "delivered"
    rows = _event_rows(ideation_client._factory, br_id)
    assert rows[-1][3] is True  # persisted status_moved


def test_ac_stb_17_merge_goes_through_the_engine_edge_with_no_actor(ideation_client):
    from app import events as core_events

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    seen = []
    core_events.subscribe(core_events.EVENT_STATUS_TRANSITIONED, seen.append)
    try:
        assert _post(
            ideation_client, br_id, key, {"stage": "Merged", "message": "m", "status": "merged"}
        ).status_code == 201
    finally:
        core_events.unsubscribe(core_events.EVENT_STATUS_TRANSITIONED, seen.append)
    mine = [p for p in seen if p.get("record_id") == br_id]
    assert [p["transition_id"] for p in mine] == ["br-tr-build-delivered"]
    assert mine[0]["actor_id"] is None


def test_ac_stb_17_second_merged_on_delivered_br_stores_without_error(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    body = {"stage": "Merged", "message": "m", "status": "merged"}
    assert _post(ideation_client, br_id, key, body).json()["statusMoved"] is True
    again = _post(ideation_client, br_id, key, body)
    assert again.status_code == 201, again.text
    assert again.json()["statusMoved"] is False
    assert br_status_key(ideation_client, h, br_id) == "delivered"
    assert len(_event_rows(ideation_client._factory, br_id)) == 3  # sent + 2


@pytest.mark.parametrize("status", ["failed", "cancelled", "in_progress"])
def test_ac_stb_17_other_statuses_store_and_never_move_the_br(ideation_client, status):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, {"stage": "Build", "message": "m", "status": status})
    assert res.status_code == 201, res.text
    assert res.json()["statusMoved"] is False
    assert br_status_key(ideation_client, h, br_id) == "sent_to_build"
    assert _event_rows(ideation_client._factory, br_id)[-1][2] == status


def test_ac_stb_17_merged_on_a_br_sent_back_to_ready_stores_only(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = insert_sent_br(ideation_client._factory, product_id=pid, status_key="ready")
    key = mint_key_via_api(ideation_client, h)["plaintext"]
    res = _post(ideation_client, br_id, key, {"stage": "Merged", "message": "m", "status": "merged"})
    assert res.status_code == 201, res.text
    assert res.json()["statusMoved"] is False
    assert br_status_key(ideation_client, h, br_id) == "ready"


# ── AC-STB-18 append-only + BR scoped ────────────────────────────────────────


def test_ac_stb_18_other_tenants_key_gets_404_on_this_tenants_br(
    ideation_client, ideation_session_factory
):
    ensure_other_tenant(ideation_session_factory)
    h = _auth(ideation_client)
    _pid, br_id, _key = _sent(ideation_client, h)
    foreign_key = insert_key_row(ideation_session_factory, OTHER_TENANT_ID)["plaintext"]
    res = _post(ideation_client, br_id, foreign_key, {"stage": "Merged", "message": "m", "status": "merged"})
    assert res.status_code == 404, res.text
    assert br_status_key(ideation_client, h, br_id) == "sent_to_build"  # not moved
    assert len(_event_rows(ideation_client._factory, br_id)) == 1


def test_ac_stb_18_no_update_or_delete_routes_for_events(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    ev = _post(ideation_client, br_id, key).json()
    for method in ("put", "patch", "delete"):
        res = getattr(ideation_client, method)(
            f"/ideation/build/{br_id}/events/{ev['id']}", headers=bearer(key)
        )
        assert res.status_code in (404, 405), (method, res.status_code)
    assert len(_event_rows(ideation_client._factory, br_id)) == 2


def test_ac_stb_18_a_build_key_cannot_read_or_change_the_br(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    k = bearer(key)
    assert ideation_client.get(f"/ideation/business-requirements/{br_id}", headers=k).status_code in (401, 403)
    assert ideation_client.get(f"/ideation/business-requirements/{br_id}/build", headers=k).status_code in (401, 403)
    assert ideation_client.post(
        f"/ideation/business-requirements/{br_id}/status", headers=k, json={"status": "delivered"}
    ).status_code in (401, 403)
    assert ideation_client.get("/ideation/build-keys", headers=k).status_code in (401, 403)
    assert br_status_key(ideation_client, h, br_id) == "sent_to_build"


# ── AC-STB-22 failure isolation (write-back side) ────────────────────────────


def test_ac_stb_22_merged_on_an_archived_br_stores_and_reports_not_moved(
    ideation_client, ideation_session_factory
):
    """The graph has no archived -> delivered edge: the refused move must not
    fail the write-back. Control: the same call on a sent BR does move."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    key = mint_key_via_api(ideation_client, h)["plaintext"]
    archived = insert_sent_br(ideation_session_factory, product_id=pid, status_key="archived")
    control = insert_sent_br(ideation_session_factory, product_id=pid)

    res = _post(ideation_client, archived, key, {"stage": "Merged", "message": "m", "status": "merged"})
    assert res.status_code == 201, res.text
    assert res.json()["statusMoved"] is False
    assert br_status_key(ideation_client, h, archived) == "archived"
    rows = _event_rows(ideation_client._factory, archived)
    assert rows[-1][:3] == ("crew", "Merged", "merged") and rows[-1][3] is False

    ok = _post(ideation_client, control, key, {"stage": "Merged", "message": "m", "status": "merged"})
    assert ok.status_code == 201 and ok.json()["statusMoved"] is True
    assert br_status_key(ideation_client, h, control) == "delivered"


# ── SEC F1: a key of a suspended tenant / inactive module is refused ─────────


def _assert_service_not_enabled(res):
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "service_not_enabled"


def _five_bad_then_throttled(client, br_id):
    """A recorded failure would shorten this run: 5 bad keys must all 401 and
    the 6th must 429 (default policy), i.e. the 403 above consumed no budget."""
    bad = bearer("fxb_live_" + "z" * 32)
    for _ in range(5):
        r = client.post(f"/ideation/build/{br_id}/events", headers=bad, json=GOOD)
        assert r.status_code == 401, r.text
    assert client.post(f"/ideation/build/{br_id}/events", headers=bad, json=GOOD).status_code == 429


def test_sec_f1_ac_stb_16_suspended_tenant_key_403(ideation_client, ideation_session_factory):
    from app.models.tenant import Tenant

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    assert _post(ideation_client, br_id, key).status_code == 201  # control: live tenant works
    db = ideation_session_factory()
    try:
        tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        tenant.status.blocks_access = True
        db.commit()
        assert tenant.signin_allowed is False
    finally:
        db.close()

    res = _post(ideation_client, br_id, key)
    _assert_service_not_enabled(res)
    assert len(_event_rows(ideation_client._factory, br_id)) == 2  # sent + control only
    _five_bad_then_throttled(ideation_client, br_id)


def test_sec_f1_ac_stb_16_archived_tenant_key_403(ideation_client, ideation_session_factory):
    from app.models.tenant import Tenant

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    db = ideation_session_factory()
    try:
        tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        tenant.status.is_archived = True
        db.commit()
    finally:
        db.close()
    _assert_service_not_enabled(_post(ideation_client, br_id, key))


def test_sec_f1_ac_stb_16_inactive_module_key_403(ideation_client, ideation_session_factory):
    from app.services.app_store_service import AppStoreService

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    assert _post(ideation_client, br_id, key).status_code == 201  # control
    db = ideation_session_factory()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "ideation")
        db.commit()
    finally:
        db.close()

    _assert_service_not_enabled(_post(ideation_client, br_id, key))
    assert len(_event_rows(ideation_client._factory, br_id)) == 2
    _five_bad_then_throttled(ideation_client, br_id)


def test_sec_f1_ac_stb_16_refused_key_does_not_stamp_last_used(
    ideation_client, ideation_session_factory
):
    """Mirrors the pull gateway: a key refused for service-not-enabled must not
    record usage it never got."""
    from app.services.app_store_service import AppStoreService
    from modules.ideation.models import BrBuildKey

    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    db = ideation_session_factory()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "ideation")
        db.commit()
        _assert_service_not_enabled(_post(ideation_client, br_id, key))
        db.expire_all()
        assert all(k.last_used_at is None for k in db.query(BrBuildKey).all())
    finally:
        db.close()


# ── R15: an explicit null status defaults like an omitted one ────────────────


def test_r15_ac_stb_16_null_status_is_in_progress(ideation_client):
    h = _auth(ideation_client)
    _pid, br_id, key = _sent(ideation_client, h)
    res = _post(ideation_client, br_id, key, {"stage": "x", "message": "y", "status": None})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "in_progress"
    assert _event_rows(ideation_client._factory, br_id)[-1][2] == "in_progress"
