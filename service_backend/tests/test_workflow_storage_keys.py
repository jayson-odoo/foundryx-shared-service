"""Workflow storage nodes (`storage.put` / `storage.get` / `storage.delete`) reach
only the calling tenant's own keys.

Required behaviour:
1. `storage.put` stores under `workflows/<tenant id>/` on every backend.
2. `storage.get` / `storage.delete` accept only: (a) `conn:<id>:<raw>` on a
   connection owned by the calling tenant, (b) `conn:<platform id>:<raw>` with raw
   under `workflows/<calling tenant id>/`, (c) a bare key under that prefix.
3. Every other key raises `ActionError` with one shared message, and the storage
   adapter is never reached.
4. Malformed `conn:` keys raise `ActionError`.
5. put -> get -> delete round trip works on local disk, the platform connection and
   the tenant's own connection.
6. The existing key-shape checks stay.
7. The rule lives in the nodes: `TenantStorage` still serves server-written keys on
   the platform row.
"""
import uuid
from dataclasses import dataclass
from typing import Optional

import pytest

from app.models.connection import CONNECTION_STATUS_UNVERIFIED, Connection
from app.models.status import Status
from app.models.tenant import PLATFORM_TENANT_ID, Tenant
from app.integrations.s3_provider import S3CompatibleAdapter
from app.secrets import encrypt_secret
from app.services import storage as storage_module
from app.services.storage import storage_for_tenant
from app.workflow_engine.actions import storage_actions
from app.workflow_engine.actions.storage_actions import ActionError

from tests.test_storage_providers import StubS3Client


class RecordingClient(StubS3Client):
    def __init__(self):
        super().__init__()
        self.deleted: list = []

    def delete_object(self, Bucket, Key):  # noqa: N803 - boto3 casing
        self.deleted.append(Key)
        super().delete_object(Bucket, Key)


@pytest.fixture
def client(monkeypatch):
    stub = RecordingClient()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: stub)
    storage_module.clear_adapter_cache()
    yield stub
    storage_module.clear_adapter_cache()


@pytest.fixture
def media(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _tenant(db, slug: str) -> Tenant:
    status_id = db.query(Status.id).filter(Status.entity_type == "tenant").first()[0]
    row = Tenant(name=slug, slug=slug, status_id=status_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _connection(db, tenant_id: str) -> Connection:
    row = Connection(
        tenant_id=tenant_id,
        provider="s3",
        type="storage",
        name="Bucket",
        config_json={"bucket": "assets", "region": "auto", "cdnBaseUrl": ""},
        credentials_json=encrypt_secret({"accessKeyId": "ak", "secretAccessKey": "sk"}),
        status=CONNECTION_STATUS_UNVERIFIED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@dataclass
class World:
    db: object
    a: str
    b: str
    platform_tenant: str
    platform_conn: Optional[str]
    a_conn: Optional[str]
    b_conn: Optional[str]
    missing_conn: str

    def fmt(self, template: str) -> str:
        return template.format(
            A=self.a,
            B=self.b,
            P=self.platform_conn or self.missing_conn,
            AC=self.a_conn or self.missing_conn,
            BC=self.b_conn or self.missing_conn,
            MISSING=self.missing_conn,
        )


def _world(session_factory, *, platform: bool, a_own: bool, b_own: bool) -> World:
    db = session_factory()
    suffix = uuid.uuid4().hex[:8]
    a = _tenant(db, f"wfk-a-{suffix}")
    b = _tenant(db, f"wfk-b-{suffix}")
    assert a.id != b.id
    return World(
        db=db,
        a=a.id,
        b=b.id,
        platform_tenant=PLATFORM_TENANT_ID,
        platform_conn=_connection(db, PLATFORM_TENANT_ID).id if platform else None,
        a_conn=_connection(db, a.id).id if a_own else None,
        b_conn=_connection(db, b.id).id if b_own else None,
        missing_conn=str(uuid.uuid4()),
    )


@pytest.fixture
def shared(session_factory, client, media):
    """Platform connection + tenant B's own connection; A has none."""
    w = _world(session_factory, platform=True, a_own=False, b_own=True)
    yield w
    w.db.close()


@pytest.fixture
def own(session_factory, client, media):
    """Platform connection + A's own connection + B's own connection."""
    w = _world(session_factory, platform=True, a_own=True, b_own=True)
    yield w
    w.db.close()


@pytest.fixture
def local(session_factory, client, media):
    """No storage connection anywhere: local disk only."""
    w = _world(session_factory, platform=False, a_own=False, b_own=False)
    yield w
    w.db.close()


NODES = {"get": storage_actions.storage_get, "delete": storage_actions.storage_delete}
both = pytest.mark.parametrize("node", ["get", "delete"])


def _run(world, node, tenant, key, ctx=None):
    return NODES[node](world.db, tenant, {"key": key}, ctx or {})


def _seed_everything(world, client, media):
    """Objects behind every refused key, so 'still there' is meaningful."""
    for raw in [
        "documents/x",
        "x",
        f"workflows/{world.b}/x",
        f"workflows/{world.a}x/y",
        f"workflows/{world.a}",
        f"Workflows/{world.a}/x",
        f"/workflows/{world.a}/x",
        "anything",
    ]:
        client.objects[raw] = b"data"
    for rel in ["documents/x", f"workflows/{world.b}/x", f"workflows/{world.b}/real.txt"]:
        path = media / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")


def _assert_untouched(client, media, world):
    assert client.presigned == []
    assert client.deleted == []
    for rel in ["documents/x", f"workflows/{world.b}/x", f"workflows/{world.b}/real.txt"]:
        assert (media / rel).exists()


# ---- rules 2 and 3: refused keys --------------------------------------------

REFUSED_KEYS = [
    pytest.param("conn:{P}:documents/x", id="platform_row_outside_prefix"),
    pytest.param("conn:{P}:x", id="platform_row_bare_raw"),
    pytest.param("conn:{P}:workflows/{B}/x", id="platform_row_other_tenant_prefix"),
    pytest.param("conn:{P}:workflows/{A}x/y", id="prefix_lookalike_id_plus_chars"),
    pytest.param("conn:{P}:workflows/{A}", id="prefix_lookalike_no_trailing_part"),
    pytest.param("conn:{P}:Workflows/{A}/x", id="prefix_lookalike_capitalised"),
    pytest.param("conn:{P}:/workflows/{A}/x", id="prefix_lookalike_leading_slash"),
    pytest.param("conn:{P}:workflows/{A}/../{B}/x", id="traversal_inside_prefix"),
    pytest.param("conn:{P}:workflows\\{A}\\..\\{B}\\x", id="traversal_inside_prefix_backslashes"),
    pytest.param("conn:{BC}:anything", id="other_tenants_connection"),
    pytest.param("conn:{MISSING}:anything", id="connection_that_does_not_exist"),
    pytest.param("documents/x", id="bare_key_outside_prefix"),
    pytest.param("workflows/{B}/x", id="bare_key_other_tenant_prefix"),
    pytest.param("workflows/{B}/real.txt", id="bare_key_existing_file_of_other_tenant"),
    pytest.param("CONN:{P}:workflows/{A}/x", id="uppercase_conn_prefix_is_a_bare_key"),
    pytest.param(" conn:{P}:documents/x", id="leading_whitespace_then_platform_outside_prefix"),
]


@both
@pytest.mark.parametrize("template", REFUSED_KEYS)
def test_a_key_outside_the_tenants_reach_is_refused(shared, client, media, node, template):
    _seed_everything(shared, client, media)
    with pytest.raises(ActionError):
        _run(shared, node, shared.a, shared.fmt(template))
    _assert_untouched(client, media, shared)


@both
def test_a_merge_rendered_key_on_the_platform_row_outside_the_prefix_is_refused(shared, client, media, node):
    _seed_everything(shared, client, media)
    ctx = {"trigger.input.k": shared.fmt("conn:{P}:documents/x")}
    with pytest.raises(ActionError):
        _run(shared, node, shared.a, "{{ trigger.input.k }}", ctx)
    _assert_untouched(client, media, shared)


@both
def test_the_refusal_text_does_not_tell_the_reasons_apart(shared, client, media, node):
    _seed_everything(shared, client, media)
    messages = []
    for template in [
        "conn:{MISSING}:documents/x",  # missing connection
        "conn:{BC}:documents/x",  # another tenant's connection
        "conn:{P}:documents/x",  # platform row outside the prefix
    ]:
        with pytest.raises(ActionError) as info:
            _run(shared, node, shared.a, shared.fmt(template))
        messages.append(str(info.value))
    assert messages[0] == messages[1] == messages[2]


@both
@pytest.mark.parametrize("key", ["conn:", "conn:x", "conn:x:"])
def test_a_malformed_connection_key_is_an_action_error(shared, client, media, node, key):
    _seed_everything(shared, client, media)
    with pytest.raises(ActionError):
        _run(shared, node, shared.a, key)
    _assert_untouched(client, media, shared)


# ---- positive controls: the same backends, allowed keys reach the adapter -----

def test_control_get_on_the_platform_row_under_the_tenant_prefix_reaches_the_adapter(shared, client, media):
    raw = f"workflows/{shared.a}/report.txt"
    client.objects[raw] = b"data"
    out = _run(shared, "get", shared.a, f"conn:{shared.platform_conn}:{raw}")
    assert client.presigned == [raw]
    assert out["url"].startswith("https://signed.example/")
    assert out["mime"] == "text/plain"


def test_control_delete_on_the_platform_row_under_the_tenant_prefix_reaches_the_adapter(shared, client, media):
    raw = f"workflows/{shared.a}/report.txt"
    client.objects[raw] = b"data"
    out = _run(shared, "delete", shared.a, f"conn:{shared.platform_conn}:{raw}")
    assert out == {"deleted": True}
    assert client.deleted == [raw]
    assert raw not in client.objects


def test_control_get_a_bare_key_under_the_tenant_prefix_returns_url_size_and_mime(shared, client, media):
    rel = f"workflows/{shared.a}/note.txt"
    (media / rel).parent.mkdir(parents=True, exist_ok=True)
    (media / rel).write_bytes(b"12345")
    out = _run(shared, "get", shared.a, rel)
    assert out["url"] == str(media / rel)
    assert out["size"] == 5
    assert out["mime"] == "text/plain"


def test_control_delete_a_bare_key_under_the_tenant_prefix_removes_the_file(shared, client, media):
    rel = f"workflows/{shared.a}/note.txt"
    (media / rel).parent.mkdir(parents=True, exist_ok=True)
    (media / rel).write_bytes(b"12345")
    _run(shared, "delete", shared.a, rel)
    assert not (media / rel).exists()


def test_control_a_merge_rendered_allowed_key_works(shared, client, media):
    raw = f"workflows/{shared.a}/report.txt"
    client.objects[raw] = b"data"
    ctx = {"trigger.input.k": f"conn:{shared.platform_conn}:{raw}"}
    _run(shared, "get", shared.a, "{{ trigger.input.k }}", ctx)
    assert client.presigned == [raw]


@both
@pytest.mark.parametrize("raw", ["documents/x", "plain-name"])
def test_a_key_on_the_tenants_own_connection_is_accepted_with_any_raw(own, client, media, node, raw):
    client.objects[raw] = b"data"
    _run(own, node, own.a, f"conn:{own.a_conn}:{raw}")
    if node == "get":
        assert client.presigned == [raw]
    else:
        assert client.deleted == [raw]


@both
@pytest.mark.parametrize("raw", ["documents/x", "anything/at/all"])
def test_the_platform_tenant_may_use_the_platform_connection_with_any_raw(shared, client, media, node, raw):
    client.objects[raw] = b"data"
    _run(shared, node, PLATFORM_TENANT_ID, f"conn:{shared.platform_conn}:{raw}")
    if node == "get":
        assert client.presigned == [raw]
    else:
        assert client.deleted == [raw]


# ---- local disk refusals leave the files alone --------------------------------

@both
@pytest.mark.parametrize(
    "template",
    [
        "documents/x",
        "workflows/{B}/x",
        "workflows/{B}/real.txt",
        "CONN:{P}:workflows/{A}/x",
        " documents/x",
    ],
)
def test_on_local_disk_a_key_outside_the_tenant_prefix_is_refused_and_the_file_stays(local, client, media, node, template):
    _seed_everything(local, client, media)
    with pytest.raises(ActionError):
        _run(local, node, local.a, local.fmt(template))
    _assert_untouched(client, media, local)


# ---- rule 1: put stores under the tenant prefix -------------------------------

def _put(world, tenant, key="report.txt"):
    return storage_actions.storage_put(world.db, tenant, {"key": key, "content": "hello"}, {})


def test_put_on_local_disk_stores_under_the_tenant_prefix(local, client, media):
    out = _put(local, local.a)
    assert out["key"].startswith(f"workflows/{local.a}/")
    assert (media / out["key"]).read_bytes() == b"hello"


def test_put_on_the_platform_connection_stores_under_the_tenant_prefix(shared, client, media):
    out = _put(shared, shared.a)
    assert out["key"].startswith(f"conn:{shared.platform_conn}:workflows/{shared.a}/")
    raw = out["key"].split(":", 2)[2]
    assert client.objects[raw] == b"hello"


def test_put_on_the_tenants_own_connection_stores_under_the_tenant_prefix(own, client, media):
    out = _put(own, own.a)
    assert out["key"].startswith(f"conn:{own.a_conn}:workflows/{own.a}/")
    raw = out["key"].split(":", 2)[2]
    assert client.objects[raw] == b"hello"


def test_put_by_the_platform_tenant_uses_its_own_prefix(shared, client, media):
    out = _put(shared, PLATFORM_TENANT_ID)
    assert out["key"].startswith(f"conn:{shared.platform_conn}:workflows/{PLATFORM_TENANT_ID}/")


# ---- rule 5: round trip --------------------------------------------------------

def test_round_trip_on_local_disk(local, client, media):
    out = _put(local, local.a)
    got = _run(local, "get", local.a, out["key"])
    assert got["size"] == 5 and got["mime"] == "text/plain"
    _run(local, "delete", local.a, out["key"])
    assert not (media / out["key"]).exists()


def test_round_trip_on_the_platform_connection(shared, client, media):
    out = _put(shared, shared.a)
    raw = out["key"].split(":", 2)[2]
    client.presigned.clear()
    _run(shared, "get", shared.a, out["key"])
    assert client.presigned == [raw]
    _run(shared, "delete", shared.a, out["key"])
    assert client.deleted == [raw]
    assert raw not in client.objects


def test_round_trip_on_the_tenants_own_connection(own, client, media):
    out = _put(own, own.a)
    raw = out["key"].split(":", 2)[2]
    client.presigned.clear()
    _run(own, "get", own.a, out["key"])
    assert client.presigned == [raw]
    _run(own, "delete", own.a, out["key"])
    assert client.deleted == [raw]
    assert raw not in client.objects


# ---- rule 6: existing key-shape checks ------------------------------------------

@pytest.mark.parametrize("node", ["put", "get", "delete"])
@pytest.mark.parametrize("key", ["   ", "../x", "a/../b", "/abs", "~/x", "a\x00b", "a\\..\\b"])
def test_malformed_key_shapes_are_still_refused(local, client, media, node, key):
    fn = {"put": storage_actions.storage_put, **NODES}[node]
    with pytest.raises(ActionError):
        fn(local.db, local.a, {"key": key, "content": "x"}, {})


# ---- rule 7: the rule lives in the nodes ----------------------------------------

def test_tenant_storage_still_serves_a_server_written_key_on_the_platform_row(shared, client, media):
    client.objects["documents/x"] = b"data"
    kind, url = storage_for_tenant(shared.db, shared.a).resolve(f"conn:{shared.platform_conn}:documents/x")
    assert kind == "presigned"
    assert client.presigned == ["documents/x"]
    assert url.startswith("https://signed.example/")


# ---- additional coverage: real connections, prefix-only keys, colons in raw ------

def _assert_adapter_not_reached(client):
    assert client.presigned == []
    assert client.deleted == []


@both
@pytest.mark.parametrize("template", ["conn:{AC}", "conn:{AC}:", "conn:{P}", "conn:{P}:"])
def test_a_malformed_key_naming_a_real_connection_is_an_action_error(own, client, media, node, template):
    _seed_everything(own, client, media)
    with pytest.raises(ActionError) as info:
        _run(own, node, own.a, own.fmt(template))
    assert type(info.value) is ActionError
    _assert_adapter_not_reached(client)


@both
def test_another_tenants_connection_with_a_raw_under_the_callers_prefix_is_refused(own, client, media, node):
    raw = f"workflows/{own.a}/x"
    client.objects[raw] = b"data"
    with pytest.raises(ActionError) as info:
        _run(own, node, own.a, f"conn:{own.b_conn}:{raw}")
    with pytest.raises(ActionError) as other:
        _run(own, node, own.a, f"conn:{own.platform_conn}:documents/x")
    assert str(info.value) == str(other.value)
    _assert_adapter_not_reached(client)
    assert raw in client.objects


@both
def test_the_prefix_alone_on_the_platform_row_is_refused(shared, client, media, node):
    with pytest.raises(ActionError):
        _run(shared, node, shared.a, f"conn:{shared.platform_conn}:workflows/{shared.a}/")
    _assert_adapter_not_reached(client)


@both
def test_the_prefix_alone_as_a_bare_key_is_refused_and_the_directory_stays(local, client, media, node):
    directory = media / "workflows" / local.a
    directory.mkdir(parents=True)
    with pytest.raises(ActionError):
        _run(local, node, local.a, f"workflows/{local.a}/")
    assert directory.is_dir()
    _assert_adapter_not_reached(client)


@both
def test_a_raw_containing_a_colon_is_one_raw_on_the_tenants_own_connection(own, client, media, node):
    client.objects["a:b"] = b"data"
    _run(own, node, own.a, f"conn:{own.a_conn}:a:b")
    assert (client.presigned if node == "get" else client.deleted) == ["a:b"]


@both
def test_a_raw_containing_a_colon_is_one_raw_under_the_prefix_on_the_platform_row(shared, client, media, node):
    raw = f"workflows/{shared.a}/a:b"
    client.objects[raw] = b"data"
    _run(shared, node, shared.a, f"conn:{shared.platform_conn}:{raw}")
    assert (client.presigned if node == "get" else client.deleted) == [raw]


# ---- a connection of another type, and a refused delete ---------------------------

def _smtp_connection(db, tenant_id: str) -> Connection:
    row = Connection(
        tenant_id=tenant_id,
        provider="smtp",
        type="smtp",
        name="Mail",
        config_json={"host": "mail.example", "port": 587},
        credentials_json=encrypt_secret({"username": "u", "password": "p"}),
        status=CONNECTION_STATUS_UNVERIFIED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@both
@pytest.mark.parametrize("owner", ["caller", "platform"])
def test_a_connection_that_is_not_a_storage_connection_is_refused(own, client, media, monkeypatch, node, owner):
    builds = []
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: builds.append(1) or client)
    storage_module.clear_adapter_cache()
    if owner == "caller":
        key = f"conn:{_smtp_connection(own.db, own.a).id}:x"
    else:
        key = f"conn:{_smtp_connection(own.db, PLATFORM_TENANT_ID).id}:workflows/{own.a}/x"
    with pytest.raises(ActionError) as info:
        _run(own, node, own.a, key)
    assert type(info.value) is ActionError
    with pytest.raises(ActionError) as other:
        _run(own, node, own.a, f"conn:{own.platform_conn}:documents/x")
    assert str(info.value) == str(other.value)
    assert builds == []
    _assert_adapter_not_reached(client)


@both
def test_control_the_tenants_own_storage_row_is_reached_next_to_its_other_connections(own, client, media, monkeypatch, node):
    builds = []
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: builds.append(1) or client)
    storage_module.clear_adapter_cache()
    _smtp_connection(own.db, own.a)
    client.objects["x"] = b"data"
    _run(own, node, own.a, f"conn:{own.a_conn}:x")
    assert builds != []
    assert (client.presigned if node == "get" else client.deleted) == ["x"]


def test_a_delete_the_filesystem_refuses_is_an_action_error_without_the_server_path(local, client, media):
    directory = media / "workflows" / local.a / "sub"
    directory.mkdir(parents=True)
    (directory / "inner.txt").write_bytes(b"data")
    with pytest.raises(ActionError) as info:
        _run(local, "delete", local.a, f"workflows/{local.a}/sub")
    assert type(info.value) is ActionError
    assert str(media) not in str(info.value)
    assert directory.is_dir()
    assert (directory / "inner.txt").exists()


def test_a_refused_delete_records_its_cause_in_the_server_log(local, client, media, caplog):
    import logging

    directory = media / "workflows" / local.a / "sub"
    directory.mkdir(parents=True)
    (directory / "inner.txt").write_bytes(b"data")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ActionError):
            _run(local, "delete", local.a, f"workflows/{local.a}/sub")
    records = [r for r in caplog.records if r.levelno >= logging.WARNING and r.exc_info]
    assert records, "no WARNING record with exc_info was logged"


def test_control_a_successful_delete_logs_no_warning(local, client, media, caplog):
    import logging

    rel = f"workflows/{local.a}/note.txt"
    (media / rel).parent.mkdir(parents=True, exist_ok=True)
    (media / rel).write_bytes(b"data")
    with caplog.at_level(logging.WARNING):
        _run(local, "delete", local.a, rel)
    assert not (media / rel).exists()
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
