"""StorageKeyLocation registry + put_raw + drift test (sprint-4/10 Slice 1) -
AC-10-04..07.

Covers: put_raw path preservation on both adapters, scalar enumerate + value-
checked rewrite (+ only_keys), JSON callback rewrite with the fresh-dict-persists
assertion, and the drift test (every *_key column is registered).
"""
import json

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.template import TEMPLATE_TYPE_EMAIL, Template
from app.models.user import User
from app.services.storage import LocalDiskStorage, StorageService
from app.storage_migration import registry as reg
from app.storage_migration.registry import (
    StorageKeyLoc,
    all_key_columns,
    enumerate_keys,
    register_storage_key_location,
    registered_scalar_columns,
    rewrite_keys,
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def isolated_locations():
    """Snapshot / clear / restore the global location registry so a test can
    register a controlled set without leaking (never touches lazy_once)."""
    saved = dict(reg._LOCATIONS)
    reg._LOCATIONS.clear()
    try:
        yield
    finally:
        reg._LOCATIONS.clear()
        reg._LOCATIONS.update(saved)


# ── AC-10-04: put_raw path-preserving write ───────────────────────────────────


def test_local_put_raw_preserves_path(tmp_path):
    store = LocalDiskStorage(root=str(tmp_path))
    store.put_raw("conn-sub/dir/exact-key.bin", b"hello-bytes", "application/octet-stream")
    content, _mime = store.fetch("conn-sub/dir/exact-key.bin")
    assert content == b"hello-bytes"
    kind, value = store.resolve("conn-sub/dir/exact-key.bin")
    assert kind == "path"
    assert value.endswith("conn-sub/dir/exact-key.bin")


def test_put_raw_is_part_of_protocol():
    # Both adapters satisfy the Protocol member (structural typing check).
    from app.integrations.s3_provider import S3CompatibleAdapter

    assert hasattr(LocalDiskStorage, "put_raw")
    assert hasattr(S3CompatibleAdapter, "put_raw")
    assert hasattr(StorageService, "put_raw")


def test_s3_put_raw_uses_exact_key():
    from app.integrations.s3_provider import S3CompatibleAdapter

    class _FakeS3:
        def __init__(self):
            self.objects = {}

        def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803 - boto3 sig
            self.objects[Key] = (Body, ContentType)

        def get_object(self, Bucket, Key):  # noqa: N803
            body, ctype = self.objects[Key]

            class _B:
                def read(_self):
                    return body

            return {"Body": _B(), "ContentType": ctype}

    fake = _FakeS3()
    adapter = S3CompatibleAdapter(
        bucket="b", endpoint_url=None, region="auto",
        access_key_id="k", secret_access_key="s", client=fake,
    )
    adapter.put_raw("exact/raw/key.png", b"img", "image/png")
    assert "exact/raw/key.png" in fake.objects  # no uuid re-mint
    content, mime = adapter.fetch("exact/raw/key.png")
    assert content == b"img"
    assert mime == "image/png"


# ── AC-10-05: scalar enumerate + value-checked rewrite ────────────────────────


def _seed_avatar_users(db, keys):
    """Point the two seeded users' avatar_key at the given values."""
    users = db.query(User).order_by(User.email).limit(len(keys)).all()
    for user, key in zip(users, keys):
        user.avatar_key = key
    db.commit()
    return users


def test_scalar_enumerate_and_rewrite(db, isolated_locations):
    register_storage_key_location(
        StorageKeyLoc(model=User, column="avatar_key", tenant_column="tenant_id")
    )
    _seed_avatar_users(db, ["conn:A:foo", "conn:A:bar"])

    keys = enumerate_keys(db, "A")
    assert keys == {"conn:A:foo", "conn:A:bar"}

    affected = rewrite_keys(db, "A", "B")
    db.commit()
    assert affected == 2
    db.expire_all()
    remaining = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None)).all()}
    assert remaining == {"conn:B:foo", "conn:B:bar"}


def test_scalar_rewrite_is_value_checked(db, isolated_locations):
    """A row already pointing at conn:B: is never clobbered (LIKE 'conn:A:%')."""
    register_storage_key_location(
        StorageKeyLoc(model=User, column="avatar_key", tenant_column="tenant_id")
    )
    _seed_avatar_users(db, ["conn:A:foo", "conn:B:already"])

    assert enumerate_keys(db, "A") == {"conn:A:foo"}
    affected = rewrite_keys(db, "A", "B")
    db.commit()
    assert affected == 1
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None)).all()}
    assert vals == {"conn:B:foo", "conn:B:already"}  # the pre-B row untouched


def test_scalar_rewrite_only_keys(db, isolated_locations):
    """Only the successfully-copied keys are rewritten (Slice-2 D5)."""
    register_storage_key_location(
        StorageKeyLoc(model=User, column="avatar_key", tenant_column="tenant_id")
    )
    _seed_avatar_users(db, ["conn:A:foo", "conn:A:bar"])

    affected = rewrite_keys(db, "A", "B", only_keys={"conn:A:foo"})
    db.commit()
    assert affected == 1
    db.expire_all()
    vals = {u.avatar_key for u in db.query(User).filter(User.avatar_key.isnot(None)).all()}
    assert vals == {"conn:B:foo", "conn:A:bar"}  # bar not in only_keys → stays on A


# ── AC-10-06: JSON callback enumerate + rewrite (fresh-dict persists) ──────────


def _add_template(db, doc):
    tpl = Template(
        tenant_id=DEFAULT_TENANT_ID,
        type=TEMPLATE_TYPE_EMAIL,
        key="k-migrate-test",
        name="Migrate test",
        context="test",
        subject="s",
        doc_json=doc,
    )
    db.add(tpl)
    db.commit()
    return tpl


def test_json_enumerate_and_rewrite_persists(db, isolated_locations):
    register_storage_key_location(
        StorageKeyLoc(model=Template, json_column="doc_json", tenant_column="tenant_id")
    )
    tpl = _add_template(
        db,
        {"sections": [{"blocks": [{"type": "image", "storageKey": "conn:A:img1"}]}]},
    )

    assert enumerate_keys(db, "A") == {"conn:A:img1"}

    affected = rewrite_keys(db, "A", "B")
    db.commit()
    assert affected == 1

    # Fresh-dict reassignment persists after commit (the SQLAlchemy JSON gotcha):
    # re-fetch from the DB and confirm the nested key changed.
    db.expire_all()
    reloaded = db.query(Template).filter(Template.id == tpl.id).first()
    assert reloaded.doc_json["sections"][0]["blocks"][0]["storageKey"] == "conn:B:img1"


def test_json_rewrite_value_checked_and_only_keys(db, isolated_locations):
    register_storage_key_location(
        StorageKeyLoc(model=Template, json_column="doc_json", tenant_column="tenant_id")
    )
    tpl = _add_template(
        db,
        {
            "blocks": [
                {"storageKey": "conn:A:one"},
                {"storageKey": "conn:A:two"},
                {"storageKey": "conn:B:already"},
            ]
        },
    )

    rewrite_keys(db, "A", "B", only_keys={"conn:A:one"})
    db.commit()
    db.expire_all()
    reloaded = db.query(Template).filter(Template.id == tpl.id).first()
    keys = [b["storageKey"] for b in reloaded.doc_json["blocks"]]
    assert keys == ["conn:B:one", "conn:A:two", "conn:B:already"]


# ── AC-10-07: drift test - every *_key column is registered ────────────────────


def test_no_unregistered_storage_key_columns(db):
    """Hard CI gate: a *_key storage column without a StorageKeyLocation fails."""
    from app.database import Base
    from app.storage_migration.core_locations import ensure_core_locations
    from modules.omnichannel import models as omni_models  # noqa: F401 - populate metadata
    from modules.omnichannel.bootstrap import register_engine_entities
    from modules.omnichannel.db import OmniBase

    ensure_core_locations()
    register_engine_entities()  # idempotent - registers conversation_messages.media_key

    found = all_key_columns([Base.metadata, OmniBase.metadata])
    registered = registered_scalar_columns()
    unregistered = found - registered
    assert not unregistered, f"Unregistered storage-key columns: {sorted(unregistered)}"

    # Sanity: the reflection actually found the known scalar columns.
    assert ("users", "avatar_key") in found
    assert ("conversation_messages", "media_key") in found
