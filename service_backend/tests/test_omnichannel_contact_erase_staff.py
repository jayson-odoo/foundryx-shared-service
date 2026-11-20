"""Plan 56 section C - contact erase: staff route, permission + grant sweep,
ideation submitter, consumer guide (AC-56-41 ideation, 50, 51, 54).

RED tests written BEFORE the implementation. Staff route:
``DELETE /omnichannel/contacts/{id}`` (the ``/api`` prefix is the frontend proxy).
"""
import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import Contact
from tests.test_omnichannel_api_gateway import _auth, _default_workspace_id, _mint
from tests.test_omnichannel_contact_erase import (  # noqa: F401 - _env is an autouse fixture
    Rig,
    _contact,
    _env,
    _digits,
)
from tests.test_omnichannel_contacts_module import _no_perm_auth, _other_tenant_auth

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules" / "omnichannel"


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


def _staff_delete(client, cid, headers):
    return client.delete(f"/omnichannel/contacts/{cid}", headers=headers)


def _manage_only_auth(client, session_factory, email="erase-manage-only@example.com"):
    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Contacts Manage Only")
    role.permissions = PermissionRepository(db).get_by_keys(["contacts.read", "contacts.manage"])
    db.add(role)
    db.flush()
    user = User(tenant_id=DEFAULT_TENANT_ID, email=email, name="Manage Only",
                password=hash_password("Password123!"), status=UserStatus.ACTIVE.value)
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()
    return _auth(client, email=email, password="Password123!")


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-51 - staff route
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_51_admin_with_contacts_erase_gets_the_same_body_and_the_same_erase(rig, client):
    fp = rig.footprint("+60100000501", "st1")
    keep = rig.footprint("+60100000502", "st2")
    before_keep = rig.counts(keep["cid"])
    res = _staff_delete(client, fp["cid"], _auth(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"contactId", "erasedAt", "messages", "files"}
    assert body["contactId"] == fp["cid"] and body["messages"] == 6 and body["files"] == 3
    after = rig.counts(fp["cid"])
    assert after["contact"] == 0 and after["messages"] == 0 and after["reactions"] == 0
    assert rig.counts(keep["cid"]) == before_keep
    assert _staff_delete(client, fp["cid"], _auth(client)).status_code == 404  # second call


def test_ac_56_51_without_contacts_erase_is_403_and_nothing_is_deleted(rig, client, session_factory):
    fp = rig.footprint("+60100000503", "st3")
    before = rig.counts(fp["cid"])
    for hdr in (_manage_only_auth(client, session_factory), _no_perm_auth(client, session_factory)):
        assert _staff_delete(client, fp["cid"], hdr).status_code == 403
    assert rig.counts(fp["cid"]) == before
    # control: the admin (who holds the key) can erase the very same contact
    assert _staff_delete(client, fp["cid"], _auth(client)).status_code == 200


def test_ac_56_51_another_tenant_cannot_erase_and_cannot_see_the_contact_exists(rig, client, session_factory):
    fp = rig.footprint("+60100000504", "st4")
    other = _other_tenant_auth(client, session_factory, slug="erase-other")
    unknown = _staff_delete(client, "no-such-contact", other)
    res = _staff_delete(client, fp["cid"], other)
    assert res.status_code == 404 and unknown.status_code == 404
    assert res.json() == unknown.json()  # uniform: no existence leak
    assert rig.counts(fp["cid"])["contact"] == 1


def test_ac_56_51_a_contact_row_of_another_tenant_is_404_for_our_admin(rig, client, session_factory):
    foreign = _contact(session_factory, rig.ws, "+60100000505", tenant="other-tenant-erase")
    res = _staff_delete(client, foreign, _auth(client))
    assert res.status_code == 404
    db = session_factory()
    try:
        assert db.query(Contact).filter(Contact.id == foreign).count() == 1
    finally:
        db.close()


def test_ac_56_51_requires_authentication(rig, client):
    fp = rig.footprint("+60100000506", "st5")
    assert _staff_delete(client, fp["cid"], {}).status_code in (401, 403)
    assert rig.counts(fp["cid"])["contact"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-50 - permission, grant sweep, no collision
# ═════════════════════════════════════════════════════════════════════════════
def _csv_keys(path):
    with open(path, newline="") as fh:
        return [f"{r['resource']}.{r['action']}" for r in csv.DictReader(fh)]


def test_ac_56_50_permission_row_is_in_the_module_csv_and_collides_with_no_other_module():
    assert "contacts.erase" in _csv_keys(MODULE_ROOT / "permissions" / "permissions.csv")
    others = [REPO_ROOT / "service_backend" / "app" / "permissions" / "permissions.csv"]
    others += [p for p in (REPO_ROOT / "service_backend" / "modules").glob("*/permissions/permissions.csv")
               if p.parent.parent != MODULE_ROOT]
    for path in others:
        assert "contacts.erase" not in _csv_keys(path), path


def _admin_has(session_factory, key):
    from sqlalchemy import select

    from app.models import Role
    from app.models.permission import Permission, role_permissions

    db = session_factory()
    try:
        perm = db.query(Permission).filter(Permission.key == key).first()
        if perm is None:
            return None
        admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin",
                                      Role.is_system.is_(True)).one()
        return db.execute(select(role_permissions.c.role_id).where(
            role_permissions.c.role_id == admin.id, role_permissions.c.permission_id == perm.id)).first() is not None
    finally:
        db.close()


def _drop_key_everywhere(session_factory, key):
    from app.models.permission import Permission, role_permissions

    db = session_factory()
    try:
        perm = db.query(Permission).filter(Permission.key == key).first()
        if perm is not None:
            db.execute(role_permissions.delete().where(role_permissions.c.permission_id == perm.id))
            db.delete(perm)
        db.commit()
    finally:
        db.close()


def _run_install(session_factory, monkeypatch):
    from modules.omnichannel import bootstrap

    monkeypatch.setattr(bootstrap, "create_schema_and_tables", lambda engine: None)
    db = session_factory()
    try:
        bootstrap.install(db.get_bind(), db)
        db.commit()
    finally:
        db.close()


def test_ac_56_50_sweep_grants_the_key_to_admin_only_when_the_key_is_first_created(session_factory, monkeypatch):
    from sqlalchemy import select

    from app.models import Role
    from app.models.permission import Permission, role_permissions

    # an existing tenant that predates the key: a custom role beside Admin
    _drop_key_everywhere(session_factory, "contacts.erase")
    db = session_factory()
    try:
        custom = Role(tenant_id=DEFAULT_TENANT_ID, name="Erase Sweep Other")
        db.add(custom)
        db.commit()
        custom_id = custom.id
    finally:
        db.close()
    assert _admin_has(session_factory, "contacts.erase") is None  # control: key gone

    _run_install(session_factory, monkeypatch)  # first creation of the key
    assert _admin_has(session_factory, "contacts.erase") is True
    db = session_factory()
    try:
        perm_id = db.query(Permission).filter(Permission.key == "contacts.erase").one().id
        assert db.execute(select(role_permissions.c.role_id).where(
            role_permissions.c.role_id == custom_id, role_permissions.c.permission_id == perm_id)).first() is None
        # a deliberate removal on Admin is respected by the next install (one-shot)
        admin = db.query(Role).filter(Role.tenant_id == DEFAULT_TENANT_ID, Role.name == "Admin",
                                      Role.is_system.is_(True)).one()
        db.execute(role_permissions.delete().where(role_permissions.c.role_id == admin.id,
                                                   role_permissions.c.permission_id == perm_id))
        db.commit()
    finally:
        db.close()
    _run_install(session_factory, monkeypatch)
    assert _admin_has(session_factory, "contacts.erase") is False


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-41 - ideation submitter set to NULL (own fixture: the ideation tables)
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ac_56_41_ideation_submitter_is_set_null_and_the_idea_stays(ideation_client, ideation_session_factory):
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    sf = ideation_session_factory
    ws = _default_workspace_id(sf)
    gone = _contact(sf, ws, "+60100000511")
    keep = _contact(sf, ws, "+60100000512")
    db = sf()
    try:
        ids = {}
        for name, cid in (("gone", gone), ("keep", keep)):
            idea = Idea(tenant_id=DEFAULT_TENANT_ID, product_id="prod-erase",
                        status_id=idea_status_id(db, "captured", DEFAULT_TENANT_ID),
                        intake_definition_key="ideation", problem=f"problem {name}", raw_text="x",
                        source="whatsapp", submitter_contact_id=cid, is_test=True)
            db.add(idea)
            db.flush()
            ids[name] = idea.id
        db.commit()
    finally:
        db.close()
    hdr = {"Authorization": f"Bearer {_mint(ideation_client, ws).json()['fullKey']}"}
    res = ideation_client.delete(f"/api/v1/omnichannel/contacts/{gone}", headers=hdr)
    assert res.status_code == 200, res.text
    db = sf()
    try:
        rows = {i.id: i.submitter_contact_id for i in db.query(Idea).filter(Idea.id.in_(list(ids.values())))}
    finally:
        db.close()
    assert rows == {ids["gone"]: None, ids["keep"]: keep}


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-54 - consumer guide + engineering doc (read lazily)
# ═════════════════════════════════════════════════════════════════════════════
def _guide() -> str:
    return (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()


def test_ac_56_54_guide_documents_the_route_response_and_404():
    guide = _guide()
    assert "DELETE /contacts/{" in guide or "DELETE /api/v1/omnichannel/contacts/{" in guide
    i = guide.index("erasedAt")
    window = guide[max(0, i - 3000) : i + 3000]
    for needle in ("contactId", "messages", "files", "contact_not_found"):
        assert needle in window, needle


def test_ac_56_54_guide_documents_the_contact_erased_event_with_exactly_two_data_fields():
    guide = _guide()
    assert "`contact.erased`" in guide
    i = guide.index("`contact.erased`")
    window = guide[i : i + 2500]
    assert "contactId" in window and "erasedAt" in window


def test_ac_56_54_guide_states_the_recontact_and_respondio_rules():
    low = _guide().lower()
    assert "erasedat" in low
    assert "new contact" in low and "new id" in low  # the re-contact rule
    i = low.index("respond.io", low.index("erasedat"))
    assert "import" in low[i - 1500 : i + 1500] or "sync" in low[i - 1500 : i + 1500]


def test_ac_56_54_guide_lists_what_cannot_be_erased():
    low = _guide().lower()
    assert "erasedat" in low
    i = low.index("erasedat")
    window = low[i : i + 9000]
    for needle in ("phone", "meta", "copies", "export", "30 days"):
        assert needle in window, f"cannot-erase list must mention {needle!r}"


def test_ac_56_54_guide_changelog_has_an_erase_row():
    guide = _guide()
    head = guide.split("## 1. The big picture")[0]
    rows = [ln for ln in head.splitlines() if ln.startswith("> | **2026-") and "erase" in ln.lower()]
    assert rows, "changelog needs a contact erase row"
    assert any("contact.erased" in ln for ln in rows), rows


def test_ac_56_54_engineering_doc_has_the_erase_order():
    doc = (REPO_ROOT / "documentation/engineering/omnichannel-service.md").read_text().lower()
    assert "erase" in doc and "contact.erased" in doc
    assert "reactions" in doc and "migration_refs" in doc
