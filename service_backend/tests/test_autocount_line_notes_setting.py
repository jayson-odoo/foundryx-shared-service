"""Plan 74 (RED, B1): the AutoCount line notes database connection is a per-company setting, set in the app.

AC-74-01 column ``ac_company.line_notes_connection_id`` + module migration 0049 (single head, id <= 32 chars)
AC-74-02 ``PATCH /autocount/companies/{id}/line-notes-connection {connectionId: str | null}``
AC-74-03 ``CompanyItem`` carries ``lineNotesConnectionId`` and ``writeEnabled``
AC-74-06 no PO / SPO write reads that database yet (plan 73 behaviour is NOT in this PR)
Every test seeds its own tenant / connection / company chain.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from alembic.script import ScriptDirectory

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password
from modules.autocount.models import AcCompany
import sqlalchemy as sa

OTHER_TENANT = "tenant-other-line-notes"
MODULE_ALEMBIC = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic"


# ---- seeds ------------------------------------------------------------------------------------

def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _limited_user(db, keys: List[str], email: str) -> None:
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in PermissionRepository(db).list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("limited1234"), name="Limited",
                status=UserStatus.ACTIVE.value, email_verified_at=sa.func.now())
    user.roles = [role]
    db.add(user)
    db.commit()


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(Tenant(id=OTHER_TENANT, slug="other-co-line-notes", name="Other Co", status_id=default.status_id))
        db.commit()


def _conn(db, provider: str, *, tenant_id: str = DEFAULT_TENANT_ID, name: Optional[str] = None) -> str:
    conn = Connection(tenant_id=tenant_id, provider=provider, type="database" if provider == "sql_database" else "erp",
                      name=name or f"{provider} conn",
                      config_json={"baseUrl": "https://ac.example.com/api/db3", "userId": "ADMIN"}
                      if provider == "autocount" else {"dbType": "mssql", "host": "x", "database": "d"},
                      credentials_json=encrypt_secret({"password": "pw-1", "appId": "a"}), is_active=True)
    db.add(conn)
    db.commit()
    return conn.id


def _company(db, *, tenant_id: str = DEFAULT_TENANT_ID, with_write: bool = True, active: bool = True,
             line_notes: Optional[str] = None) -> str:
    api = _conn(db, "autocount", tenant_id=tenant_id, name="api")
    company = AcCompany(tenant_id=tenant_id, connection_id=api, database_name=f"AED_{uuid.uuid4().hex[:8]}", company_name="AED",
                        name="AED", is_active=active, write_connection_id=api if with_write else None)
    if line_notes is not None:
        company.line_notes_connection_id = line_notes
    db.add(company)
    db.commit()
    return company.id


def _url(company_id: str) -> str:
    return f"/autocount/companies/{company_id}/line-notes-connection"


def _stored(session_factory, company_id: str) -> Optional[str]:
    db = session_factory()
    try:
        db.expire_all()
        return db.query(AcCompany).filter(AcCompany.id == company_id).one().line_notes_connection_id
    finally:
        db.close()


# ---- AC-74-01 column + migration --------------------------------------------------------------

def test_ac_74_01_company_has_a_nullable_line_notes_connection_column():
    col = AcCompany.__table__.c["line_notes_connection_id"]
    assert col.nullable is True


def test_ac_74_01_migration_0049_is_the_single_head_over_0048():
    script = ScriptDirectory(str(MODULE_ALEMBIC))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    head = script.get_revision(heads[0])
    assert head.revision.startswith("0049") and len(head.revision) <= 32, head.revision
    assert str(head.down_revision).startswith("0048"), head.down_revision
    text = next((MODULE_ALEMBIC / "versions").glob("0049_*.py")).read_text()
    assert "line_notes_connection_id" in text and "ADD COLUMN IF NOT EXISTS" in text.upper()


# ---- AC-74-02 the route -------------------------------------------------------------------------

def test_ac_74_02_set_then_clear(client, session_factory):
    db = session_factory()
    company_id, sql_id = _company(db), _conn(db, "sql_database")
    db.close()
    ok = client.patch(_url(company_id), json={"connectionId": sql_id}, headers=_auth(client))
    assert ok.status_code == 200, ok.text
    assert ok.json()["lineNotesConnectionId"] == sql_id
    assert _stored(session_factory, company_id) == sql_id
    cleared = client.patch(_url(company_id), json={"connectionId": None}, headers=_auth(client))
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["lineNotesConnectionId"] is None
    assert _stored(session_factory, company_id) is None


@pytest.mark.parametrize("variant", ["wrong_provider", "other_tenant", "unknown"])
def test_ac_74_02_a_connection_that_is_not_a_same_tenant_sql_database_is_422_and_nothing_changes(
        client, session_factory, variant):
    db = session_factory()
    _other_tenant(db)
    keep = _conn(db, "sql_database", name="Existing")
    company_id = _company(db, line_notes=keep)
    bad = {"wrong_provider": lambda: _conn(db, "autocount", name="hapi"),
           "other_tenant": lambda: _conn(db, "sql_database", tenant_id=OTHER_TENANT),
           "unknown": lambda: "no-such-connection"}[variant]()
    db.close()
    r = client.patch(_url(company_id), json={"connectionId": bad}, headers=_auth(client))
    assert r.status_code == 422, r.text
    message = r.json().get("message") or ""
    assert message.strip() and bad not in message  # a plain sentence, never an id
    assert _stored(session_factory, company_id) == keep


def test_ac_74_02_another_tenants_company_is_404_and_unchanged(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    foreign = _company(db, tenant_id=OTHER_TENANT)
    sql_id = _conn(db, "sql_database")
    db.close()
    own = _company(db2 := session_factory())
    db2.close()
    r = client.patch(_url(foreign), json={"connectionId": sql_id}, headers=_auth(client))
    assert r.status_code == 404, r.text
    assert _stored(session_factory, foreign) is None
    # control: the route exists, so the 404 above is the company lookup and not a missing route
    assert client.patch(_url(own), json={"connectionId": sql_id}, headers=_auth(client)).status_code == 200


def test_ac_74_02_missing_manage_permission_is_403_and_unchanged(client, session_factory):
    db = session_factory()
    company_id, sql_id = _company(db), _conn(db, "sql_database")
    _limited_user(db, ["autocount.companies.read"], "reader-ln@example.com")
    db.close()
    headers = _auth(client, "reader-ln@example.com", "limited1234")
    r = client.patch(_url(company_id), json={"connectionId": sql_id}, headers=headers)
    assert r.status_code == 403, r.text
    assert _stored(session_factory, company_id) is None


def test_ac_74_02_body_without_connection_id_is_422(client, session_factory):
    db = session_factory()
    company_id = _company(db)
    db.close()
    assert client.patch(_url(company_id), json={}, headers=_auth(client)).status_code == 422


def test_ac_74_02_set_is_idempotent(client, session_factory):
    db = session_factory()
    company_id, sql_id = _company(db), _conn(db, "sql_database")
    db.close()
    for _ in range(2):
        assert client.patch(_url(company_id), json={"connectionId": sql_id}, headers=_auth(client)).status_code == 200
    assert _stored(session_factory, company_id) == sql_id


# ---- AC-74-03 the company wire shape --------------------------------------------------------------

def test_ac_74_03_detail_and_list_carry_line_notes_connection_id_and_write_enabled(client, session_factory):
    db = session_factory()
    sql_id = _conn(db, "sql_database")
    enabled = _company(db, line_notes=sql_id)
    bare = _company(db, with_write=False)
    inactive = _company(db, active=False)
    db.close()
    h = _auth(client)
    d_enabled = client.get(f"/autocount/companies/{enabled}", headers=h).json()["company"]
    assert d_enabled["lineNotesConnectionId"] == sql_id and d_enabled["writeEnabled"] is True
    d_bare = client.get(f"/autocount/companies/{bare}", headers=h).json()["company"]
    assert d_bare["lineNotesConnectionId"] is None and d_bare["writeEnabled"] is False
    d_inactive = client.get(f"/autocount/companies/{inactive}", headers=h).json()["company"]
    assert d_inactive["writeEnabled"] is False  # a write connection on an INACTIVE company does not enable writes
    listed = {c["id"]: c for c in client.get("/autocount/companies?page_size=200", headers=h).json()["data"]}
    assert listed[enabled]["writeEnabled"] is True and listed[enabled]["lineNotesConnectionId"] == sql_id
    assert listed[bare]["writeEnabled"] is False


def test_ac_74_03_wire_never_carries_a_url_or_key_for_write_enabled(client, session_factory):
    db = session_factory()
    company_id = _company(db)
    db.close()
    body = client.get(f"/autocount/companies/{company_id}", headers=_auth(client)).json()["company"]
    text = str(body)
    assert "ac.example.com" not in text and "pw-1" not in text and "writeConnectionId" not in body


# ---- AC-74-06 no write reads the database in this PR ------------------------------------------------

from tests.test_autocount_write_back_primitives import _line, db, h  # noqa: E402,F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: E402,F401


def test_ac_74_06_a_po_write_is_unchanged_and_never_reads_the_line_notes_database(h, monkeypatch):
    from modules.autocount.sql_source.runtime import SqlSourceRuntime

    sql_id = _conn(h.db, "sql_database")
    h.company.line_notes_connection_id = sql_id  # set, but plan 73 is not in this PR
    h.db.commit()

    def boom(*a, **kw):
        raise AssertionError("a PO write read the line notes database")

    monkeypatch.setattr(SqlSourceRuntime, "readonly_connection", boom)
    doc = h.seed_doc("PO", 7001, [_line("ITEM-A", 4, 5.0, "HQ")])
    res = h.edit("PO", 7001, line_changes=[{"DtlKey": doc["Details"][0]["DtlKey"], "Qty": 3}])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert [c for c in h.vendor.writes() if c.method == "PUT"]


def test_ac_74_02_patch_answer_carries_the_companys_source_kind(client, session_factory):
    db = session_factory()
    company_id, sql_id = _company(db), _conn(db, "sql_database")
    db.close()
    r = client.patch(_url(company_id), json={"connectionId": sql_id}, headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["sourceKind"] == "api"  # the company reads through its API connection, not the default
