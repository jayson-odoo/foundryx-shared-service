"""Plan 63 (RED): the production-only write gate, AC-63-10..15.

Writable books = code ceiling {db1, db3} AND ``settings.autocount_write_allowed_books_list`` AND
(the test books {db3} unless ``settings.environment == "production"`` exactly). The host digest rule
is unchanged. ``assert_test_company`` skips its live-book check only for a book that is writable and
not a test book. Everything is read per call. No test opens db1 against a real host: the host is the
pinned ``ac.example.test`` and the vendor is the in-process fake.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import List

import httpx
import pytest

from app.config import Settings, settings
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcApiCallLog, AcEntityConfig, AcWriteAction
from modules.autocount.write_back import guard
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.guard import WriteConnectionError, WriteNotAllowed, assert_write_allowed
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB1 = "https://ac.example.test/api/db1"
DB1_OTHER_HOST = "https://other.example.test/api/db1"
ROOT = Path(__file__).resolve().parents[2]
LIST_DEFAULT = Settings.model_fields["autocount_write_allowed_books"].default if "autocount_write_allowed_books" in Settings.model_fields else "db3"


def _set(monkeypatch, *, env: str, books: str) -> None:
    monkeypatch.setattr(settings, "environment", env)
    monkeypatch.setattr(settings, "autocount_write_allowed_books", books)


# ------------------------------------------------------------------ AC-63-10 constants, settings, matrix

def test_ac_63_10_constants():
    assert guard.TEST_BOOKS == frozenset({"db3"})
    assert guard.WRITE_ALLOWED_BOOKS == frozenset({"db1", "db3"})
    assert isinstance(guard.TEST_BOOKS, frozenset) and isinstance(guard.WRITE_ALLOWED_BOOKS, frozenset)


def test_ac_63_10_the_setting_defaults_to_db3_and_parses_a_comma_list(monkeypatch):
    assert "autocount_write_allowed_books" in Settings.model_fields
    assert Settings.model_fields["autocount_write_allowed_books"].default == "db3"
    monkeypatch.setattr(settings, "autocount_write_allowed_books", " db1 , db3 ,, ")
    assert list(settings.autocount_write_allowed_books_list) == ["db1", "db3"]
    monkeypatch.setattr(settings, "autocount_write_allowed_books", "")
    assert list(settings.autocount_write_allowed_books_list) == []


ENVS = ["development", "test", "production", "Production", ""]
BOOKS = ["db1", "db2", "db3", "db4"]
LISTS = [LIST_DEFAULT, "db3", "db1", "db1,db3", " db1 , db3 "]


def _expected(env: str, book: str, books: str) -> bool:
    listed = book in {b.strip() for b in books.split(",")}
    return book in {"db1", "db3"} and listed and (book == "db3" or env == "production")


@pytest.mark.parametrize("env,book,books", list(itertools.product(ENVS, BOOKS, LISTS)))
def test_ac_63_10_matrix_writable_books_and_assert_write_allowed(monkeypatch, env, book, books):
    _set(monkeypatch, env=env, books=books)
    expected = _expected(env, book, books)
    assert (book in guard.writable_books()) is expected
    url = f"https://ac.example.test/api/{book}"
    if expected:
        assert assert_write_allowed(url) == book
    else:
        with pytest.raises(WriteNotAllowed) as ei:
            assert_write_allowed(url)
        assert ei.value.code == "WRITE_NOT_ALLOWED"


@pytest.mark.parametrize("env", ENVS)
def test_ac_63_10_writable_books_is_exactly_the_formula(monkeypatch, env):
    _set(monkeypatch, env=env, books="db1,db3")
    assert guard.writable_books() == frozenset(
        b for b in ("db1", "db2", "db3", "db4") if _expected(env, b, "db1,db3"))


def test_ac_63_10_the_env_list_can_never_widen_past_the_code_ceiling(monkeypatch):
    _set(monkeypatch, env="production", books="db1,db2,db3,db4,db99")
    assert guard.writable_books() == frozenset({"db1", "db3"})
    with pytest.raises(WriteNotAllowed):
        assert_write_allowed("https://ac.example.test/api/db2")


def test_ac_63_12_the_host_digest_rule_is_unchanged_in_production(monkeypatch):
    _set(monkeypatch, env="production", books="db1,db3")
    assert assert_write_allowed(DB1) == "db1"
    for url in (DB1_OTHER_HOST, "https://other.example.test/api/db3", "http://ac.example.test/api/db1",
                "https://ac.example.test/api/db1?x=1", "https://ac.example.test/api/DB1"):
        with pytest.raises(WriteNotAllowed):
            assert_write_allowed(url)


# ------------------------------------------------------------------ rig

@pytest.fixture
def gw(h, db):
    return Gw(h, db)


def _point_at(h, url: str) -> None:
    h.conn.config_json = {"baseUrl": url, "userId": "ADMIN", "auth": "none"}
    h.db.commit()


def _edit(client, gw, doc_key=6900, idem="gate-1"):
    return client.patch(f"{PREFIX}/documents/sales-orders/{doc_key}", headers=gw.hdr(idem),
                        json={"companyCode": "SRT", "header": {"ref": "x"}})


def _seed(h, key=6900):
    h.seed_doc("SO", key, [_line("A", 10, 5.0)])


def _logs(h) -> List[AcApiCallLog]:
    s = h.session_factory()
    try:
        return s.query(AcApiCallLog).order_by(AcApiCallLog.created_at).all()
    finally:
        s.close()


# ------------------------------------------------------------------ AC-63-11 db1 refused off production

@pytest.mark.parametrize("env", ["development", "test", "Production", ""])
def test_ac_63_11_db1_off_production_is_refused_before_any_request(client, gw, monkeypatch, env):
    h = gw.h
    _set(monkeypatch, env=env, books="db1,db3")
    _point_at(h, DB1)
    _seed(h)
    r = _edit(client, gw)
    assert r.status_code == 403 and code(r) == "WRITE_NOT_ALLOWED", r.text
    assert h.vendor.calls == []
    h.db.expire_all()
    assert h.db.query(AcWriteAction).one().error_code == "WRITE_NOT_ALLOWED"


def test_ac_63_11_the_refusal_leaves_exactly_one_guard_refused_call_log_row(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="development", books="db1,db3")
    _point_at(h, DB1)
    _seed(h)
    assert code(_edit(client, gw)) == "WRITE_NOT_ALLOWED"
    rows = _logs(h)
    assert len(rows) == 1, [(r.method, r.outcome) for r in rows]
    assert rows[0].outcome == "guard_refused" and rows[0].error_code == "WRITE_NOT_ALLOWED"
    assert rows[0].book == "db1" and rows[0].response_status is None


def test_ac_63_11_control_db3_off_production_still_writes(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="development", books="db1,db3")
    _seed(h)
    r = _edit(client, gw)
    assert r.status_code == 200, r.text
    assert [c.method for c in h.vendor.writes()] == ["PUT"]


def _cli(fresh, monkeypatch, capsys, session_factory, url):
    import app.database as database
    from app.models.tenant import Tenant
    from modules.autocount.write_back import admin

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    slug = fresh.db.get(Tenant, DEFAULT_TENANT_ID).slug
    conn = fresh._connection(url, DEFAULT_TENANT_ID)
    code_ = admin.main(["set-write-connection", "--tenant-slug", slug, "--company-id", fresh.company.id,
                        "--connection-id", conn.id])
    return code_, capsys.readouterr().out, conn


@pytest.fixture
def fresh(h):
    h.company.write_connection_id = None
    h.db.commit()
    return h


def _wc(fresh) -> str:
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    return fresh.company.write_connection_id


def test_ac_63_11_cli_set_write_connection_for_db1_off_production(fresh, monkeypatch, capsys, session_factory):
    _set(monkeypatch, env="development", books="db1,db3")
    code_, out, _conn = _cli(fresh, monkeypatch, capsys, session_factory, DB1)
    assert code_ == 2 and out.strip() == "error: WRITE_NOT_ALLOWED"
    assert _wc(fresh) is None


def test_ac_63_12_cli_set_write_connection_for_db1_in_production_is_ok(fresh, monkeypatch, capsys, session_factory):
    _set(monkeypatch, env="production", books="db1,db3")
    code_, out, conn = _cli(fresh, monkeypatch, capsys, session_factory, DB1)
    assert code_ == 0 and out.strip() == "ok"
    assert _wc(fresh) == conn.id


def test_ac_63_12_cli_refuses_db1_in_production_when_the_list_lacks_it(fresh, monkeypatch, capsys, session_factory):
    _set(monkeypatch, env="production", books="db3")
    code_, out, _conn = _cli(fresh, monkeypatch, capsys, session_factory, DB1)
    assert code_ == 2 and out.strip() == "error: WRITE_NOT_ALLOWED"
    assert _wc(fresh) is None


def test_ac_63_13_cli_db1_with_a_sql_source_is_ok_in_production_only(fresh, monkeypatch, capsys, session_factory):
    fresh.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=fresh.company.id, entity_type="customer",
                                source_impl=SOURCE_IMPL_SQL_DB))
    fresh.db.commit()
    _set(monkeypatch, env="production", books="db1,db3")
    code_, out, conn = _cli(fresh, monkeypatch, capsys, session_factory, DB1)
    assert code_ == 0 and out.strip() == "ok" and _wc(fresh) == conn.id


def test_ac_63_13_cli_db3_with_a_sql_source_is_still_refused_in_production(fresh, monkeypatch, capsys, session_factory):
    fresh.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=fresh.company.id, entity_type="customer",
                                source_impl=SOURCE_IMPL_SQL_DB))
    fresh.db.commit()
    _set(monkeypatch, env="production", books="db1,db3")
    code_, out, _conn = _cli(fresh, monkeypatch, capsys, session_factory, DB3)
    assert code_ == 2 and out.strip() == "error: WRITE_COMPANY_NOT_TEST"
    assert _wc(fresh) is None


# ------------------------------------------------------------------ AC-63-12 production db1

def test_ac_63_12_production_with_db1_listed_a_db1_write_goes_out(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="production", books="db1,db3")
    _point_at(h, DB1)
    _seed(h)
    r = _edit(client, gw)
    assert r.status_code == 200, r.text
    assert [c.method for c in h.vendor.writes()] == ["PUT"]
    rows = _logs(h)
    assert rows and {x.book for x in rows} == {"db1"} and all(x.outcome == "ok" for x in rows)


def test_ac_63_12_production_with_db1_listed_but_a_synced_company_still_writes(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="production", books="db1,db3")
    _point_at(h, DB1)
    doc = h.seed_doc("SO", 6901, [_line("A", 10, 5.0)], stage=False)
    h.stage("SO", doc, job_id="sql-sync-job")  # a production company always holds synced rows
    r = _edit(client, gw, 6901, "gate-sync")
    assert r.status_code == 200, r.text
    assert [c.method for c in h.vendor.writes()] == ["PUT"]


def test_ac_63_12_production_with_db1_not_listed_is_refused(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="production", books="db3")
    _point_at(h, DB1)
    _seed(h)
    r = _edit(client, gw)
    assert code(r) == "WRITE_NOT_ALLOWED" and h.vendor.calls == []


def test_ac_63_12_production_db1_on_another_host_is_refused(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="production", books="db1,db3")
    _point_at(h, DB1_OTHER_HOST)
    _seed(h)
    r = _edit(client, gw)
    assert code(r) == "WRITE_NOT_ALLOWED" and h.vendor.calls == []


def test_ac_63_12_production_db3_synced_company_is_still_refused_as_not_test(client, gw, monkeypatch):
    h = gw.h
    _set(monkeypatch, env="production", books="db1,db3")
    doc = h.seed_doc("SO", 6902, [_line("A", 10, 5.0)], stage=False)
    h.stage("SO", doc, job_id="sql-sync-job")
    r = _edit(client, gw, 6902, "gate-db3sync")
    assert code(r) == "WRITE_COMPANY_NOT_TEST" and h.vendor.calls == []


def test_ac_63_13_off_production_db1_synced_company_is_not_test_even_if_the_book_were_listed(h, monkeypatch):
    # the book gate comes first off production, but the live-book check itself must still refuse
    _set(monkeypatch, env="development", books="db1,db3")
    doc = h.seed_doc("SO", 6903, [_line("A", 10, 5.0)], stage=False)
    h.stage("SO", doc, job_id="sql-sync-job")
    for book in (None, "db1", "db3", "db2"):
        with pytest.raises(WriteConnectionError) as ei:
            guard.assert_test_company(h.db, DEFAULT_TENANT_ID, h.company.id, book=book)
        assert ei.value.code == "WRITE_COMPANY_NOT_TEST", book


# ------------------------------------------------------------------ AC-63-13 assert_test_company matrix

def _live(h, how: str) -> None:
    if how == "sql":
        h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="customer",
                                source_impl=SOURCE_IMPL_SQL_DB))
        h.db.commit()
    elif how == "rows":
        doc = h.seed_doc("PO", 7101, [_line("A", 10, 5.0)], stage=False)
        h.stage("PO", doc, job_id="sql-sync-job")
    elif how == "so_rows":
        doc = h.seed_doc("SO", 7102, [_line("A", 10, 5.0)], stage=False)
        h.stage("SO", doc, job_id="sql-sync-job")


def _passes(h, book) -> bool:
    try:
        guard.assert_test_company(h.db, DEFAULT_TENANT_ID, h.company.id, book=book)
    except WriteConnectionError as exc:
        assert exc.code == "WRITE_COMPANY_NOT_TEST"
        return False
    return True


@pytest.mark.parametrize("how", ["sql", "rows", "so_rows"])
@pytest.mark.parametrize("env,books,book,passes", [
    ("development", "db1,db3", "db1", False),
    ("development", "db1,db3", "db3", False),
    ("development", "db1,db3", None, False),
    ("test", "db1,db3", "db1", False),
    ("Production", "db1,db3", "db1", False),
    ("production", "db1,db3", "db1", True),
    ("production", "db1,db3", "db3", False),
    ("production", "db1,db3", None, False),
    ("production", "db3", "db1", False),
    ("production", "db1,db3", "db2", False),
])
def test_ac_63_13_live_company_matrix(h, monkeypatch, how, env, books, book, passes):
    _set(monkeypatch, env=env, books=books)
    _live(h, how)
    assert _passes(h, book) is passes


def test_ac_63_13_control_a_clean_company_passes_everywhere(h, monkeypatch):
    for env, book in itertools.product(("development", "production"), (None, "db1", "db3", "db2")):
        _set(monkeypatch, env=env, books="db1,db3")
        assert _passes(h, book), (env, book)


def test_ac_63_13_write_back_own_staged_rows_never_count(h, monkeypatch):
    _set(monkeypatch, env="development", books="db1,db3")
    h.seed_doc("SO", 7103, [_line("A", 10, 5.0)])  # staged by the write-back job
    assert _passes(h, "db3")


# ------------------------------------------------------------------ AC-63-14 read per call

def test_ac_63_14_the_next_write_sees_a_changed_environment_and_list(client, gw, monkeypatch):
    h = gw.h
    _point_at(h, DB1)
    _seed(h)
    _set(monkeypatch, env="development", books="db1,db3")
    assert code(_edit(client, gw, idem="flip-1")) == "WRITE_NOT_ALLOWED" and h.vendor.calls == []
    monkeypatch.setattr(settings, "environment", "production")
    assert _edit(client, gw, idem="flip-2").status_code == 200
    assert len(h.vendor.writes()) == 1
    monkeypatch.setattr(settings, "autocount_write_allowed_books", "db3")
    before = len(h.vendor.calls)
    assert code(_edit(client, gw, idem="flip-3")) == "WRITE_NOT_ALLOWED"
    assert len(h.vendor.calls) == before


def test_ac_63_14_a_client_built_earlier_follows_the_setting_without_recreation(monkeypatch):
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    _set(monkeypatch, env="production", books="db1,db3")
    client = AutoCountWriteClient(DB1, transport=httpx.MockTransport(handler))
    assert client.put("/EditSalesOrderbydockey", {"a": 1}).ok and len(calls) == 1  # control: it writes
    monkeypatch.setattr(settings, "environment", "development")
    with pytest.raises(WriteNotAllowed) as ei:
        client.put("/EditSalesOrderbydockey", {"a": 1})
    assert ei.value.code == "WRITE_NOT_ALLOWED" and len(calls) == 1
    monkeypatch.setattr(settings, "environment", "production")
    assert client.put("/EditSalesOrderbydockey", {"a": 1}).ok and len(calls) == 2


def test_ac_63_14_constructing_a_client_for_db1_off_production_raises(monkeypatch):
    _set(monkeypatch, env="development", books="db1,db3")
    with pytest.raises(WriteNotAllowed):
        AutoCountWriteClient(DB1, transport=httpx.MockTransport(lambda r: httpx.Response(200)))


# ------------------------------------------------------------------ AC-63-15 deploy plumbing

def test_ac_63_15_compose_carries_the_env_line_in_the_shared_backend_env_block():
    lines = (ROOT / "docker-compose.yml").read_text().splitlines()
    want = "  AUTOCOUNT_WRITE_ALLOWED_BOOKS: ${AUTOCOUNT_WRITE_ALLOWED_BOOKS:-db3}"
    assert want in lines
    anchor = lines.index("x-backend-env: &backend-env")
    services = next(i for i, ln in enumerate(lines) if ln == "services:")
    assert anchor < lines.index(want) < services


def test_ac_63_15_deploy_env_content_carries_the_variable_with_a_db3_default():
    text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    want = "AUTOCOUNT_WRITE_ALLOWED_BOOKS=${{ vars.AUTOCOUNT_WRITE_ALLOWED_BOOKS || 'db3' }}"
    assert want in text
    assert text.index("ENV_CONTENT: |") < text.index(want)
