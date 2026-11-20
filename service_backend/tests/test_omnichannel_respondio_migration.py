"""Plan 33 (roadmap A6), slice S1 - respond.io connection provider, throttled
API client, preflight, migration permissions (AC-MIG-11..17).

Two layers: (1) ``RespondIoClient`` unit tests against a stubbed
``httpx.MockTransport`` - pacing/retry/backoff/pagination asserted with fake
``sleep``/``monotonic``/``rand`` so nothing here waits in real time (the
``WhatsAppCloudAdapter`` test pattern, ``tests/test_omnichannel.py``); (2)
route/service tests over the real API (provider registration, connection
CRUD, test(), preflight, tenant isolation).
"""
import itertools
import json

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

from modules.omnichannel.respondio.channel_map import (
    DOCUMENTED_SOURCE_VALUES,
    SOURCE_TO_CHANNEL_TYPE,
    target_channel_type_for,
)
from modules.omnichannel.respondio.client import (
    MAX_ATTEMPTS,
    RATE_HALVE_THRESHOLD,
    RespondIoClient,
    RespondIoError,
)


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(client, headers) -> str:
    res = client.get("/omnichannel/workspaces", headers=headers)
    assert res.status_code == 200
    return next(w["id"] for w in res.json()["data"] if w["isDefault"])


def _no_throttle_client(
    handler,
    *,
    sleep_calls=None,
    rand_value: float = 0.0,
    requests_per_second: float = 1000.0,
    on_milestone=None,
) -> RespondIoClient:
    """A client whose THROTTLE never fires (huge fake monotonic steps) so
    retry/backoff tests only see backoff-related sleeps."""
    calls = sleep_calls if sleep_calls is not None else []
    counter = itertools.count()

    def monotonic() -> float:
        return next(counter) * 1000.0

    def sleep(seconds: float) -> None:
        calls.append(seconds)

    return RespondIoClient(
        api_token="tok",
        requests_per_second=requests_per_second,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep,
        monotonic=monotonic,
        rand=lambda: rand_value,
        on_milestone=on_milestone,
    )


# ── channel_map (AC-MIG-31 coverage, pinned here since S1 owns the file) ────


def test_channel_map_covers_every_documented_source_value():
    for source in DOCUMENTED_SOURCE_VALUES:
        assert source in SOURCE_TO_CHANNEL_TYPE, source
        assert SOURCE_TO_CHANNEL_TYPE[source]  # non-empty target type
    # No undocumented row sneaked in either - the map and the pinned list agree.
    assert set(SOURCE_TO_CHANNEL_TYPE) == set(DOCUMENTED_SOURCE_VALUES)


def test_channel_map_unknown_source_has_no_target():
    assert target_channel_type_for("some_future_channel") is None


# ── RespondIoClient: pagination ─────────────────────────────────────────────


def test_pagination_cursor_walking_over_a_stubbed_transport():
    seen_cursor_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursorId")
        seen_cursor_ids.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": 1, "name": "A", "source": "whatsapp"}],
                    "pagination": {"next": "c1"},
                },
            )
        assert cursor == "c1"
        return httpx.Response(
            200,
            json={
                "items": [{"id": 2, "name": "B", "source": "facebook"}],
                "pagination": {"next": None},
            },
        )

    client = _no_throttle_client(handler)
    items = client.list_space_channels()
    assert [i["id"] for i in items] == [1, 2]
    assert seen_cursor_ids == [None, "c1"]


def test_list_contacts_paginates_over_post_with_required_timezone():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        cursor = request.url.params.get("cursorId")
        if cursor is None:
            return httpx.Response(
                200, json={"items": [{"id": 1}], "pagination": {"next": "c1"}}
            )
        return httpx.Response(200, json={"items": [{"id": 2}], "pagination": {"next": None}})

    client = _no_throttle_client(handler)
    items = list(client.list_contacts(timezone="Asia/Kuala_Lumpur"))
    assert [i["id"] for i in items] == [1, 2]
    assert all(b["timezone"] == "Asia/Kuala_Lumpur" for b in bodies)


# ── RespondIoClient: retry / backoff / rate limiting (D-A6-5, AC-MIG-15) ────


def test_retry_after_header_honoured_exactly():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after": "2.5"}, json={"message": "slow down"})
        return httpx.Response(200, json={"items": [], "pagination": {}})

    sleep_calls = []
    client = _no_throttle_client(handler, sleep_calls=sleep_calls)
    client.list_space_channels()
    assert 2.5 in sleep_calls


def test_backoff_ceiling_raises_after_max_attempts_on_repeated_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": 500, "message": "upstream error"})

    sleep_calls = []
    client = _no_throttle_client(handler, sleep_calls=sleep_calls, rand_value=0.0)
    with pytest.raises(RespondIoError) as exc_info:
        client.list_space_channels()
    assert exc_info.value.status_code == 500
    assert len(sleep_calls) == MAX_ATTEMPTS - 1
    # rand=0 -> pure exponential (0.5 * 2**(attempt-1)) for each backoff wait.
    assert sleep_calls == pytest.approx([0.5, 1.0, 2.0, 4.0])


def test_rate_halves_after_fourth_consecutive_429_then_recovers():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= RATE_HALVE_THRESHOLD:
            return httpx.Response(429, json={"message": "rate limited"})
        return httpx.Response(200, json={"items": [], "pagination": {}})

    milestones = []
    client = _no_throttle_client(
        handler, requests_per_second=8.0, on_milestone=milestones.append
    )
    client.list_space_channels()  # succeeds on the 5th attempt (== MAX_ATTEMPTS)
    assert client._rps == pytest.approx(4.0)
    assert len(milestones) == 1
    assert "halving" in milestones[0]


def test_non_429_4xx_raises_typed_error_with_vendor_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": 40401, "message": "Contact not found"})

    client = _no_throttle_client(handler)
    with pytest.raises(RespondIoError) as exc_info:
        client.list_space_channels()
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == 40401
    assert exc_info.value.message == "Contact not found"


def test_client_self_throttles_to_configured_rate():
    """requests_per_second=2 -> min interval 0.5s; a second call landing only
    0.1s after the first must wait the remaining 0.4s (AC-MIG-15)."""
    clock = iter([0.0, 0.1, 0.5])
    sleep_calls = []

    client = RespondIoClient(
        api_token="tok",
        requests_per_second=2.0,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        ),
        sleep=lambda s: sleep_calls.append(s),
        monotonic=lambda: next(clock),
        rand=lambda: 0.0,
    )
    client.ping()
    client.ping()
    assert sleep_calls == pytest.approx([0.4])


# ── Provider registration + fields() shape (AC-MIG-11) ──────────────────────


def test_respondio_provider_registered_with_expected_fields_shape(client):
    """Hits the real HTTP surface so registration-at-boot is proven end to
    end, not just importable."""
    res = client.get("/integrations/providers", headers=_auth(client))
    assert res.status_code == 200
    entry = next(p for p in res.json() if p["provider"] == "respondio")
    assert entry["type"] == "migration"
    keys = {f["key"] for f in entry["fields"]}
    assert keys == {"spaceLabel", "timezone", "apiToken", "requestsPerSecond", "baseUrl"}
    by_key = {f["key"]: f for f in entry["fields"]}
    assert by_key["apiToken"]["secret"] is True
    assert by_key["timezone"]["required"] is True
    assert by_key["baseUrl"]["defaultValue"] == "https://api.respond.io/v2"
    assert by_key["requestsPerSecond"]["defaultValue"] == "4"


# ── Connection CRUD generic behaviour, exercised through OUR provider ───────


def _create_connection(client, headers, *, api_token="secret-token-xyz") -> str:
    res = client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "respondio",
            "name": "Acme Space",
            "config": {
                "spaceLabel": "Acme Support",
                "timezone": "Asia/Kuala_Lumpur",
                "requestsPerSecond": "4",
            },
            "credentials": {"apiToken": api_token},
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_blank_secret_keeps_stored_value_and_partial_config_merges(client, session_factory):
    h = _auth(client)
    connection_id = _create_connection(client, h)

    # Partial config PATCH (adds baseUrl) must not wipe spaceLabel/timezone;
    # a blank apiToken must keep the stored token (AC-MIG-12).
    res = client.patch(
        f"/integrations/connections/{connection_id}",
        headers=h,
        json={"config": {"baseUrl": "https://api.respond.io/v2"}, "credentials": {"apiToken": ""}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["config"]["spaceLabel"] == "Acme Support"
    assert body["config"]["timezone"] == "Asia/Kuala_Lumpur"
    assert body["config"]["baseUrl"] == "https://api.respond.io/v2"
    # Credentials are write-only - never echoed on any read.
    assert "credentials" not in body
    assert "apiToken" not in body

    from app.secrets import decrypt_secret
    from app.models.connection import Connection

    db = session_factory()
    try:
        row = db.query(Connection).filter(Connection.id == connection_id).first()
        assert decrypt_secret(row.credentials_json)["apiToken"] == "secret-token-xyz"
    finally:
        db.close()


def _patch_client_factory(monkeypatch, handler, *, sleep=lambda s: None):
    """Route ``RespondIoClient.from_connection`` (shared by the provider's
    ``test()`` and ``MigrationPreflightService``) through a stubbed
    transport, keeping the REAL client's throttle/retry/error-mapping code
    in the loop end to end."""

    def fake_from_connection(config, credentials, *, client=None, on_milestone=None, on_blocker=None):
        return RespondIoClient(
            base_url=str(config.get("baseUrl") or "https://api.respond.io/v2"),
            api_token=str(credentials.get("apiToken", "")),
            requests_per_second=float(config.get("requestsPerSecond") or 4),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            on_milestone=on_milestone,
            on_blocker=on_blocker,
            sleep=sleep,
        )

    monkeypatch.setattr(RespondIoClient, "from_connection", staticmethod(fake_from_connection))


def test_connection_test_success(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    _patch_client_factory(monkeypatch, lambda r: httpx.Response(200, json={"items": []}))

    res = client.post(f"/integrations/connections/{connection_id}/test", headers=h, json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True


def test_connection_test_401_reports_token_rejected_no_token_leak(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h, api_token="super-secret-value")
    _patch_client_factory(
        monkeypatch, lambda r: httpx.Response(401, json={"code": 401, "message": "Unauthorized"})
    )

    res = client.post(f"/integrations/connections/{connection_id}/test", headers=h, json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "rejected" in body["message"].lower()
    assert "super-secret-value" not in body["message"]
    assert "Traceback" not in body["message"]


def test_connection_test_403_reports_plan_tier(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    _patch_client_factory(
        monkeypatch, lambda r: httpx.Response(403, json={"code": 403, "message": "Forbidden"})
    )

    res = client.post(f"/integrations/connections/{connection_id}/test", headers=h, json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "developer api" in body["message"].lower()
    assert "growth plan" in body["message"].lower()


# ── Preflight route (AC-MIG-14, 51, 52) ─────────────────────────────────────


def _space_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/space/channel"):
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": 10, "name": "Main WA", "source": "whatsapp_cloud"},
                    {"id": 11, "name": "FB Page", "source": "facebook"},
                ],
                "pagination": {"next": None},
            },
        )
    if path.endswith("/space/user"):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 20,
                        "firstName": "Jane",
                        "lastName": "Doe",
                        "email": "jane@example.com",
                        "role": "agent",
                        "team": {"id": 30, "name": "Support"},
                    },
                    {
                        "id": 21,
                        "firstName": "No",
                        "lastName": "Team",
                        "email": "no-team@example.com",
                        "role": "agent",
                        "team": None,
                    },
                ],
                "pagination": {"next": None},
            },
        )
    if path.endswith("/space/custom_field"):
        return httpx.Response(
            200,
            json={
                "items": [{"id": 40, "name": "Membership", "dataType": "text"}],
                "pagination": {"next": None},
            },
        )
    if path.endswith("/contact/list"):
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": 1, "lifecycle": "Trial"},
                    {"id": 2, "lifecycle": "Customer"},
                    {"id": 3, "lifecycle": None},
                ],
                "pagination": {"next": None},
            },
        )
    raise AssertionError(f"unexpected path {path}")


def test_preflight_success_shape(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _space_handler)

    res = client.get(
        "/omnichannel/migration/preflight",
        headers=h,
        params={"connectionId": connection_id, "workspaceId": ws_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["apiAvailable"] is True
    assert {c["source"] for c in body["channels"]} == {"whatsapp_cloud", "facebook"}
    assert len(body["users"]) == 2
    assert body["teams"] == [{"id": "30", "name": "Support"}]
    assert body["fields"] == [{"id": "40", "name": "Membership", "dataType": "text"}]
    assert set(body["lifecycles"]) == {"Trial", "Customer"}
    # No connected target channel exists yet in a fresh workspace - both
    # source channels are reported as having no compatible target.
    assert any("FB Page" in w or "Main WA" in w for w in body["warnings"])


def test_preflight_plan_tier_blocker_reports_api_unavailable(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(
        monkeypatch, lambda r: httpx.Response(403, json={"code": 403, "message": "Forbidden"})
    )

    res = client.get(
        "/omnichannel/migration/preflight",
        headers=h,
        params={"connectionId": connection_id, "workspaceId": ws_id},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["apiAvailable"] is False
    assert body["channels"] == []
    assert any("growth plan" in w.lower() for w in body["warnings"])


def test_preflight_requires_manage_permission(client, session_factory):
    """A role holding only `omnichannel_migration.read` (never `.manage`) must
    get 403 on preflight (AC-MIG-50)."""
    from app.models import Permission, Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    db = session_factory()
    read_perm = (
        db.query(Permission).filter(Permission.key == "omnichannel_migration.read").first()
    )
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Migration Reader")
    role.permissions = [read_perm]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="reader@example.com",
        password=hash_password("Password123!"),
        name="Reader",
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    h = _auth(client, email="reader@example.com", password="Password123!")
    res = client.get(
        "/omnichannel/migration/preflight",
        headers=h,
        params={"connectionId": "whatever", "workspaceId": "whatever"},
    )
    assert res.status_code == 403


def test_connection_resolution_is_tenant_scoped(client, session_factory):
    """A respond.io connection created by tenant A must read back as a plain
    404 (never leak existence) to tenant B - never a bare `get(id)` (AC-
    MIG-14/51/52)."""
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Tenant",
        slug="other-rio",
        admin_email="admin-other-rio@example.com",
        admin_password="Password123!",
        admin_name="Admin",
    )
    db.flush()
    other_tenant_id = tenant.id
    AppStoreService(db).install(other_tenant_id, "omnichannel")
    db.commit()
    db.close()
    h2 = _auth(client, email="admin-other-rio@example.com", password="Password123!", tenant_slug="other-rio")

    res = client.get(
        "/omnichannel/migration/preflight",
        headers=h2,
        params={"connectionId": connection_id, "workspaceId": ws_id},
    )
    assert res.status_code == 404

    from modules.omnichannel.repositories.migration_connection_repository import (
        MigrationConnectionRepository,
    )

    db2 = session_factory()
    try:
        assert (
            MigrationConnectionRepository(db2).get_for_provider(
                other_tenant_id, connection_id, "respondio"
            )
            is None
        )
        assert (
            MigrationConnectionRepository(db2).get_for_provider(
                DEFAULT_TENANT_ID, connection_id, "respondio"
            )
            is not None
        )
    finally:
        db2.close()


def test_preflight_unknown_connection_id_is_uniform_404(client):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    res = client.get(
        "/omnichannel/migration/preflight",
        headers=h,
        params={"connectionId": "does-not-exist", "workspaceId": ws_id},
    )
    assert res.status_code == 404
