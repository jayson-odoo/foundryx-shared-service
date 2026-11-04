"""Plan 58 - every contact erase writes one register row (AC-58-01..03, 10..17).

RED tests written BEFORE the implementation. Black box: HTTP routes, the
register table read directly, the service signature. Names of the unwritten
code are imported INSIDE each test so one missing name hides no other test.

Seams the implementation must honour:
* model ``ContactErasure`` (table ``contact_erasures``, check ``ck_contact_erasures_actor``);
* ``EraseActor.staff(user_id)`` / ``EraseActor.api_key(key_id)`` in
  ``modules/omnichannel/services/contact_erase_service.py``;
* required keyword ``actor=`` on ``ContactEraseService.erase`` / ``erase_in_tenant``;
* ``ContactEraseRepository.add_erasure(...)`` writes the row in the erase transaction;
* migration ``0026_omni_contact_erasures`` revising ``0025_omni_migration_sync``.

Every test seeds its own chain. Fake values only.
"""
import ast
import inspect
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import Contact, ConversationMessage
from tests.conftest import ACTIVE_EMAIL
from tests.test_omnichannel_api_gateway import _auth, _mint, _seed_second_workspace
from tests.test_omnichannel_contact_erase import (  # noqa: F401 - _env is an autouse fixture
    BASE,
    Rig,
    _contact,
    _digits,
    _env,
)
from tests.test_omnichannel_contacts_module import _no_perm_auth, _other_tenant_auth
from tests.test_omnichannel_webhooks import _process, _wa_payload

VERSIONS = Path(__file__).resolve().parents[1] / "modules" / "omnichannel" / "alembic" / "versions"
MIGRATION = VERSIONS / "0026_omni_contact_erasures.py"


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


# ── helpers ──────────────────────────────────────────────────────────────────
def _rows(sf):
    from modules.omnichannel.models import ContactErasure

    db = sf()
    try:
        return db.query(ContactErasure).order_by(ContactErasure.erased_at).all()
    finally:
        db.close()


def _snapshot(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _wire_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _staff_user_id(sf):
    from app.models import User

    db = sf()
    try:
        return db.query(User).filter(User.email == ACTIVE_EMAIL, User.tenant_id == DEFAULT_TENANT_ID).one().id
    finally:
        db.close()


def _staff_delete(client, cid, headers):
    return client.delete(f"/omnichannel/contacts/{cid}", headers=headers)


def _key(client, ws, name="Erase key"):
    body = _mint(client, ws, name).json()
    return body["key"]["id"], {"Authorization": f"Bearer {body['fullKey']}"}


def _present(rig, cid):
    c = rig.counts(cid)
    return c["contact"], c["messages"]


def _new_row(sf, **kw):
    from modules.omnichannel.models import ContactErasure

    base = dict(tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-x", contact_id="c-x",
                actor_kind="staff", actor_user_id="u-1", api_key_id=None,
                messages=0, files=0, erased_at=datetime.now(timezone.utc))
    base.update(kw)
    db = sf()
    try:
        db.add(ContactErasure(**base))
        db.flush()
    finally:
        db.rollback()
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-01 / 02 - the table and the actor check
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_01_columns_nullability_and_no_foreign_keys():
    from modules.omnichannel.models import ContactErasure

    t = ContactErasure.__table__
    assert t.name == "contact_erasures"
    assert t.schema in (None, "app_omnichannel")
    assert {c.name for c in t.columns} == {
        "id", "tenant_id", "workspace_id", "contact_id", "actor_kind", "actor_user_id",
        "api_key_id", "messages", "files", "erased_at"}
    assert [c.name for c in t.primary_key.columns] == ["id"]
    for name in ("tenant_id", "workspace_id", "contact_id", "actor_kind", "messages", "files", "erased_at"):
        assert t.c[name].nullable is False, name
    for name in ("actor_user_id", "api_key_id"):
        assert t.c[name].nullable is True, name
    assert not any(c.foreign_keys for c in t.columns)
    assert type(t.c.erased_at.type).__name__ == "UTCDateTime"
    assert t.c.messages.type.python_type is int and t.c.files.type.python_type is int
    assert any(getattr(k, "name", None) == "ck_contact_erasures_actor" for k in t.constraints)


def test_ac_58_02_actor_check_accepts_the_two_valid_shapes_and_refuses_the_rest(session_factory):
    # controls: both valid shapes flush
    _new_row(session_factory, actor_kind="staff", actor_user_id="u-1", api_key_id=None)
    _new_row(session_factory, actor_kind="api_key", actor_user_id=None, api_key_id="k-1")
    for bad in (
        dict(actor_kind="staff", actor_user_id=None, api_key_id=None),
        dict(actor_kind="api_key", actor_user_id=None, api_key_id=None),
        dict(actor_kind="staff", actor_user_id="u-1", api_key_id="k-1"),
        dict(actor_kind="api_key", actor_user_id="u-1", api_key_id="k-1"),
        dict(actor_kind="staff", actor_user_id=None, api_key_id="k-1"),
        dict(actor_kind="api_key", actor_user_id="u-1", api_key_id=None),
        dict(actor_kind="bot", actor_user_id="u-1", api_key_id=None),
        dict(actor_kind="bot", actor_user_id=None, api_key_id="k-1"),
    ):
        with pytest.raises(IntegrityError):
            _new_row(session_factory, **bad)


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-03 - migration file (the live Postgres probe is the lead's job)
# ═════════════════════════════════════════════════════════════════════════════
def _assigned(src, name):
    for node in ast.parse(src).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if target is not None and getattr(target, "id", None) == name:
            return ast.literal_eval(node.value)
    return None


def test_ac_58_03_migration_revision_chain_and_single_head():
    assert MIGRATION.exists()
    src = MIGRATION.read_text()
    rev = _assigned(src, "revision")
    assert rev == "0026_omni_contact_erasures" and len(rev) <= 32
    assert _assigned(src, "down_revision") == "0025_omni_migration_sync"
    assert "def upgrade" in src and "def downgrade" in src
    assert "contact_erasures" in src and "ck_contact_erasures_actor" in src
    # idempotent like 0025: an inspector guard
    assert "inspect" in src
    # single head: every revision is some other file's parent except exactly one
    revs, parents = set(), set()
    for f in VERSIONS.glob("*.py"):
        text = f.read_text()
        r = _assigned(text, "revision")
        if r:
            revs.add(r)
            p = _assigned(text, "down_revision")
            if p:
                parents.add(p)
    assert revs - parents == {"0026_omni_contact_erasures"}


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-10 - staff erase
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_10_staff_erase_writes_one_row_equal_to_the_response(rig, client, session_factory):
    fp = rig.footprint("+60100000701", "r10")
    assert _rows(session_factory) == []  # control: nothing before
    res = _staff_delete(client, fp["cid"], _auth(client))
    assert res.status_code == 200, res.text
    body = res.json()
    rows = _rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_kind == "staff"
    assert row.actor_user_id == _staff_user_id(session_factory)
    assert row.api_key_id is None
    assert (row.tenant_id, row.workspace_id, row.contact_id) == (DEFAULT_TENANT_ID, rig.ws, fp["cid"])
    assert row.messages == body["messages"] == 6
    assert row.files == body["files"] == 3
    assert _utc(row.erased_at) == _wire_dt(body["erasedAt"])


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-11 - API key erase
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("form", ["id", "phone"])
def test_ac_58_11_api_key_erase_writes_one_row_with_the_key_id(rig, client, session_factory, form):
    from app.models.integration_activity import SOURCE_INBOUND_API, IntegrationActivity

    phone = "+60100000702" if form == "id" else "+60100000703"
    fp = rig.footprint(phone, f"r11{form}")
    key_id, hdr = _key(client, rig.ws)
    db = session_factory()
    before = db.query(IntegrationActivity).filter(IntegrationActivity.source == SOURCE_INBOUND_API).count()
    db.close()
    ident = f"id:{fp['cid']}" if form == "id" else f"phone:{phone}"
    res = client.delete(f"{BASE}/{ident}", headers=hdr)
    assert res.status_code == 200, res.text
    body = res.json()
    rows = _rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_kind == "api_key" and row.api_key_id == key_id and row.actor_user_id is None
    assert (row.tenant_id, row.workspace_id, row.contact_id) == (DEFAULT_TENANT_ID, rig.ws, fp["cid"])
    assert row.messages == body["messages"] and row.files == body["files"]
    assert _utc(row.erased_at) == _wire_dt(body["erasedAt"])
    db = session_factory()
    try:
        after = db.query(IntegrationActivity).filter(IntegrationActivity.source == SOURCE_INBOUND_API).count()
    finally:
        db.close()
    assert after == before + 1  # the request's own activity row is still written


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-12 - same transaction
# ═════════════════════════════════════════════════════════════════════════════
def _service(sf):
    from modules.omnichannel.services.contact_erase_service import ContactEraseService

    db = sf()
    return db, ContactEraseService(db)


def test_ac_58_12_failure_in_the_row_deletes_leaves_no_row_and_the_contact(rig, session_factory, monkeypatch):
    from modules.omnichannel.repositories.contact_erase_repository import ContactEraseRepository
    from modules.omnichannel.services.contact_erase_service import EraseActor

    fp = rig.footprint("+60100000711", "r12a")
    ok = rig.footprint("+60100000712", "r12ok")

    def boom(self, *a, **k):
        raise RuntimeError("forced failure")

    with monkeypatch.context() as m:
        m.setattr(ContactEraseRepository, "delete_events", boom)
        db, svc = _service(session_factory)
        try:
            with pytest.raises(RuntimeError):
                svc.erase(DEFAULT_TENANT_ID, rig.ws, fp["cid"], actor=EraseActor.staff("u-12"))
        finally:
            db.close()
    assert _rows(session_factory) == []
    assert _present(rig, fp["cid"]) == (1, 6)
    # control: the same erase without the failure writes exactly one row
    db, svc = _service(session_factory)
    try:
        svc.erase(DEFAULT_TENANT_ID, rig.ws, ok["cid"], actor=EraseActor.staff("u-12"))
    finally:
        db.close()
    assert len(_rows(session_factory)) == 1


def test_ac_58_12_failure_writing_the_row_rolls_the_erase_back(rig, session_factory, monkeypatch):
    from modules.omnichannel.repositories.contact_erase_repository import ContactEraseRepository
    from modules.omnichannel.services.contact_erase_service import EraseActor

    fp = rig.footprint("+60100000713", "r12b")

    def boom(self, *a, **k):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(ContactEraseRepository, "add_erasure", boom)
    db, svc = _service(session_factory)
    try:
        with pytest.raises(RuntimeError):
            svc.erase(DEFAULT_TENANT_ID, rig.ws, fp["cid"], actor=EraseActor.api_key("k-12"))
    finally:
        db.close()
    assert _rows(session_factory) == []
    assert _present(rig, fp["cid"]) == (1, 6)


@pytest.mark.parametrize("route", ["staff", "key"])
def test_ac_58_12_a_failing_register_write_answers_an_error_over_http(rig, client, session_factory, monkeypatch, route):
    from modules.omnichannel.repositories.contact_erase_repository import ContactEraseRepository

    fp = rig.footprint("+60100000714" if route == "staff" else "+60100000715", f"r12{route}")
    staff_hdr = _auth(client)
    _, key_hdr = _key(client, rig.ws)

    def boom(self, *a, **k):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(ContactEraseRepository, "add_erasure", boom)
    with TestClient(app, raise_server_exceptions=False) as quiet:
        if route == "staff":
            res = _staff_delete(quiet, fp["cid"], staff_hdr)
        else:
            res = quiet.delete(f"{BASE}/{fp['cid']}", headers=key_hdr)
    assert res.status_code >= 500
    assert _rows(session_factory) == []
    assert _present(rig, fp["cid"]) == (1, 6)


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-13 - an erase that does not happen writes nothing
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_13_every_non_erase_leaves_zero_rows(rig, client, session_factory):
    own = rig.footprint("+60100000721", "r13a")
    gone = rig.footprint("+60100000722", "r13b")
    other_ws = _seed_second_workspace(session_factory)
    in_other_ws = _contact(session_factory, other_ws, "+60100000723")
    foreign_tenant = _contact(session_factory, rig.ws, "+60100000724", tenant="other-tenant-erase")
    admin = _auth(client)
    key_id, key_hdr = _key(client, rig.ws, "live")
    rev_id, rev_hdr = _key(client, rig.ws, "to revoke")
    assert client.post(f"/omnichannel/workspaces/{rig.ws}/api-keys/{rev_id}/revoke", headers=admin).status_code == 200
    _, other_ws_hdr = _key(client, other_ws, "other ws")
    other_tenant = _other_tenant_auth(client, session_factory, slug="erase-other-58")
    no_perm = _no_perm_auth(client, session_factory)

    # a second erase: seed the 404 by erasing once, then wipe that one row so the count starts at zero
    assert _staff_delete(client, gone["cid"], admin).status_code == 200
    assert len(_rows(session_factory)) == 1
    from modules.omnichannel.models import ContactErasure

    db = session_factory()
    db.query(ContactErasure).delete()
    db.commit()
    db.close()

    assert _staff_delete(client, "no-such-contact", admin).status_code == 404       # unknown id
    assert _staff_delete(client, foreign_tenant, admin).status_code == 404          # another tenant's contact
    assert _staff_delete(client, own["cid"], other_tenant).status_code == 404       # other tenant's admin
    assert _staff_delete(client, gone["cid"], admin).status_code == 404             # second erase
    assert _staff_delete(client, own["cid"], no_perm).status_code == 403            # no contacts.erase
    assert client.delete(f"{BASE}/{own['cid']}", headers={"Authorization": "Bearer fxw_live_nope"}).status_code == 401
    assert client.delete(f"{BASE}/{own['cid']}", headers=rev_hdr).status_code == 401  # revoked key
    assert client.delete(f"{BASE}/{own['cid']}", headers=other_ws_hdr).status_code == 404  # key of another workspace
    assert client.delete(f"{BASE}/{in_other_ws}", headers=key_hdr).status_code == 404       # contact of another workspace
    assert client.delete(f"{BASE}/{gone['cid']}", headers=key_hdr).status_code == 404       # second erase by key
    assert _rows(session_factory) == []
    assert _present(rig, own["cid"]) == (1, 6)
    # control: a real erase by the live key afterwards writes exactly one row
    assert client.delete(f"{BASE}/{own['cid']}", headers=key_hdr).status_code == 200
    rows = _rows(session_factory)
    assert len(rows) == 1 and rows[0].api_key_id == key_id


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-14 - no erased personal data in the row
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("route", ["staff", "key"])
def test_ac_58_14_no_erased_value_appears_in_any_column(rig, client, session_factory, route):
    from app.models import DEFAULT_TENANT_ID as _t  # noqa: F401

    name, last = "Zyxwvu-Distinct", "Qponml-Surname"
    phone, email, text = "+60177700014", "distinct.zyx@example.test", "Zyxtext-message-body-58"
    db = session_factory()
    try:
        c = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=rig.ws, first_name=name, last_name=last,
                    phone=phone, phone_digits=_digits(phone), email=email, priority="MEDIUM")
        db.add(c)
        db.flush()
        db.add(ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=c.id, channel_id=rig.channel,
                                   sender_type="CONTACT", message_type="TEXT", body=text))
        db.commit()
        cid = c.id
    finally:
        db.close()
    if route == "staff":
        res = _staff_delete(client, cid, _auth(client))
    else:
        res = client.delete(f"{BASE}/{cid}", headers=_key(client, rig.ws)[1])
    assert res.status_code == 200, res.text
    rows = _rows(session_factory)
    assert len(rows) == 1  # control: the row exists, so the absence below is meaningful
    values = " | ".join(str(v) for v in _snapshot(rows[0]).values()).lower()
    for secret in (name, last, phone, _digits(phone), email, text, "distinct.zyx"):
        assert secret.lower() not in values, secret


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-15 - the row outlives the contact
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_15_a_new_contact_gets_a_new_id_and_the_row_is_unchanged(rig, client, session_factory):
    phone = "+60100000731"
    fp = rig.footprint(phone, "r15")
    assert _staff_delete(client, fp["cid"], _auth(client)).status_code == 200
    before = [_snapshot(r) for r in _rows(session_factory)]
    assert len(before) == 1
    _process(session_factory, rig.channel, _wa_payload(wamid="wamid.r15.again", from_=_digits(phone)))
    db = session_factory()
    try:
        fresh = db.query(Contact).filter(Contact.workspace_id == rig.ws, Contact.phone_digits == _digits(phone)).all()
    finally:
        db.close()
    assert len(fresh) == 1 and fresh[0].id != fp["cid"]
    assert [_snapshot(r) for r in _rows(session_factory)] == before
    assert before[0]["contact_id"] == fp["cid"]


def test_ac_58_15_the_file_purge_leaves_the_row_unchanged(rig, client, session_factory):
    from modules.omnichannel.services.contact_erase_service import purge_files

    fp = rig.footprint("+60100000732", "r15p")
    assert _staff_delete(client, fp["cid"], _auth(client)).status_code == 200
    before = [_snapshot(r) for r in _rows(session_factory)]
    assert len(before) == 1
    purge_files(DEFAULT_TENANT_ID, list(fp["files"].values()))
    assert [_snapshot(r) for r in _rows(session_factory)] == before


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-16 - no erase path can skip the row
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_16_erase_and_erase_in_tenant_require_actor(rig, session_factory):
    from modules.omnichannel.services.contact_erase_service import ContactEraseService, EraseActor

    for fn in (ContactEraseService.erase, ContactEraseService.erase_in_tenant):
        p = inspect.signature(fn).parameters.get("actor")
        assert p is not None and p.default is inspect.Parameter.empty, fn.__name__
    fp = rig.footprint("+60100000741", "r16")
    db, svc = _service(session_factory)
    try:
        with pytest.raises(TypeError):
            svc.erase(DEFAULT_TENANT_ID, rig.ws, fp["cid"])
        with pytest.raises(TypeError):
            svc.erase_in_tenant(DEFAULT_TENANT_ID, fp["cid"])
    finally:
        db.close()
    assert _present(rig, fp["cid"]) == (1, 6)
    assert _rows(session_factory) == []
    # control: with an actor each entry point erases and writes its row
    other = rig.footprint("+60100000742", "r16b")
    db, svc = _service(session_factory)
    try:
        svc.erase_in_tenant(DEFAULT_TENANT_ID, fp["cid"], actor=EraseActor.staff("u-16"))
        svc.erase(DEFAULT_TENANT_ID, rig.ws, other["cid"], actor=EraseActor.api_key("k-16"))
    finally:
        db.close()
    assert sorted(r.actor_kind for r in _rows(session_factory)) == ["api_key", "staff"]


# ═════════════════════════════════════════════════════════════════════════════
# AC-58-17 - uninstall removes the tenant's rows only
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_58_17_uninstall_tenant_removes_that_tenants_rows_and_no_other(session_factory):
    from modules.omnichannel.bootstrap import uninstall_tenant
    from modules.omnichannel.models import ContactErasure

    def add(tenant, cid):
        return ContactErasure(tenant_id=tenant, workspace_id="ws-x", contact_id=cid, actor_kind="staff",
                              actor_user_id="u-17", api_key_id=None, messages=1, files=0,
                              erased_at=datetime.now(timezone.utc))

    db = session_factory()
    try:
        db.add_all([add("erase-t1", "c-1"), add("erase-t1", "c-2"), add("erase-t2", "c-3")])
        db.commit()
        uninstall_tenant(db, "erase-t1")
        db.commit()
        left = db.query(ContactErasure).all()
    finally:
        db.close()
    assert [(r.tenant_id, r.contact_id) for r in left] == [("erase-t2", "c-3")]
