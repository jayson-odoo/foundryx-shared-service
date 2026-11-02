"""Plan 46 review round: real driver error shapes reach the fixed sentences,
the detail goes to the server log, and the builder reads its own url."""
import logging
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app import database
from app.config import settings
from app.db_errors import db_error_text
from modules.autocount.sql_source import runtime
from modules.autocount.sql_source.runtime import sanitize_error

IDENT = "zzident9137"
HOST = "db-host-9137.invalid"
USER = "svc_user_9137"


def _wrap(orig, cls=OperationalError):
    return cls("SELECT 1", {}, orig)


def _fixed(text):
    """No host, user or identifier of the failing call rides in the text."""
    for word in (IDENT, HOST, USER, "DETAIL", "DB-Lib", "Errno"):
        assert word not in text


# ── 1. the builder reads its own url ───────────────────────────────────────


def test_ac_46_01_a_local_engine_ignores_the_deployed_database_setting(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@localhost:5432/absent")
    engine = database.build_engine("sqlite://")
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


# ── 2. real shapes reach the fixed sentences ───────────────────────────────


def _real(connect):
    try:
        connect()
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("expected a connection failure")


def test_ac_46_06_a_pymssql_connect_failure_gives_the_host_sentence():
    pymssql = pytest.importorskip("pymssql")
    orig = _real(
        lambda: pymssql.connect(
            server="127.0.0.1", port=1, user="u", password="p", database="d", login_timeout=2
        )
    )
    assert isinstance(orig.args[0], tuple), "the real shape nests the code in a tuple"
    assert sanitize_error(_wrap(orig)) == runtime._HOST_UNREACHABLE


def test_ac_46_06_a_psycopg2_refused_connection_gives_the_host_sentence():
    psycopg2 = pytest.importorskip("psycopg2")
    orig = _real(
        lambda: psycopg2.connect(
            host="127.0.0.1", port=1, user="u", password="p", dbname="d", connect_timeout=2
        )
    )
    assert orig.pgcode is None
    assert sanitize_error(_wrap(orig)) == runtime._HOST_UNREACHABLE


def test_ac_46_06_a_psycopg2_unknown_host_gives_the_host_sentence():
    psycopg2 = pytest.importorskip("psycopg2")
    orig = _real(
        lambda: psycopg2.connect(
            host="nohost.invalid", port=5432, user="u", password="p", dbname="d",
            connect_timeout=2,
        )
    )
    assert sanitize_error(_wrap(orig)) == runtime._HOST_UNREACHABLE


def _pg(message):
    psycopg2 = pytest.importorskip("psycopg2")
    return psycopg2.OperationalError(message)


PG_PREFIX = f'connection to server at "{HOST}" (10.0.0.9), port 5432 failed: '


@pytest.mark.parametrize(
    "message,expected",
    [
        (f'{PG_PREFIX}FATAL:  password authentication failed for user "{USER}"\n',
         "_LOGIN_REFUSED"),
        (f'{PG_PREFIX}FATAL:  database "{IDENT}" does not exist\n', "_DATABASE_MISSING"),
        (f"{PG_PREFIX}timeout expired\n", "_TIMED_OUT"),
    ],
)
def test_ac_46_06_a_psycopg2_connect_failure_without_a_code_gives_its_sentence(
    message, expected
):
    text = sanitize_error(_wrap(_pg(message)))
    assert text == getattr(runtime, expected)
    _fixed(text)


def test_ac_46_06_a_psycopg2_tls_required_failure_gives_a_tls_sentence():
    text = sanitize_error(
        _wrap(_pg(f"{PG_PREFIX}server does not support SSL, but SSL was required\n"))
    )
    _fixed(text)
    assert any(w in text for w in ("TLS", "SSL", "encrypt"))


def test_ac_46_06_a_pymysql_refused_and_login_errors_still_work():
    pymysql = pytest.importorskip("pymysql")
    refused = pymysql.err.OperationalError(
        2003, f"Can't connect to MySQL server on '{HOST}' ([Errno 61] Connection refused)"
    )
    login = pymysql.err.OperationalError(1045, f"Access denied for user '{USER}'@'h'")
    assert sanitize_error(_wrap(refused)) == runtime._HOST_UNREACHABLE
    assert sanitize_error(_wrap(login)) == runtime._LOGIN_REFUSED


@pytest.mark.parametrize(
    "build",
    [
        lambda: __import__("pymysql").err.OperationalError(
            2026, f"SSL connection error: certificate verify failed for {HOST}"
        ),
        lambda: __import__("pymssql").OperationalError(
            (20017, f"DB-Lib error: Unexpected EOF from the server ({HOST})".encode())
        ),
    ],
)
def test_ac_46_06_tls_failures_from_mysql_and_sql_server_give_a_tls_sentence(build):
    text = sanitize_error(_wrap(build()))
    _fixed(text)
    assert any(w in text for w in ("TLS", "SSL", "encrypt"))


@pytest.mark.parametrize(
    "build",
    [
        lambda: __import__("pymysql").err.OperationalError(
            3024, "Query execution was interrupted, maximum statement execution time exceeded"
        ),
        lambda: __import__("pymysql").err.OperationalError(
            1969, "Query execution was interrupted (max_statement_time exceeded)"
        ),
    ],
)
def test_ac_46_06_server_side_timeouts_give_the_timed_out_sentence(build):
    assert sanitize_error(_wrap(build())) == runtime._TIMED_OUT


@pytest.mark.parametrize(
    "orig_builder,word",
    [
        (lambda: __import__("pymssql").ProgrammingError(
            (208, f"Invalid object name '{IDENT}'.".encode())), "table"),
        (lambda: __import__("pymssql").ProgrammingError(
            (207, f"Invalid column name '{IDENT}'.".encode())), "column"),
        (lambda: __import__("pymysql").err.ProgrammingError(
            1146, f"Table 'db.{IDENT}' doesn't exist"), "table"),
        (lambda: __import__("pymysql").err.OperationalError(
            1054, f"Unknown column '{IDENT}' in 'field list'"), "column"),
    ],
)
def test_ac_46_06_missing_table_and_column_codes_give_a_sentence_without_identifiers(
    orig_builder, word
):
    text = sanitize_error(_wrap(orig_builder(), ProgrammingError))
    assert IDENT not in text
    assert word in text.lower()


@pytest.mark.parametrize("code,word", [("42P01", "table"), ("42703", "column")])
def test_ac_46_06_postgres_missing_table_and_column_give_a_sentence_without_identifiers(
    code, word
):
    psycopg2 = pytest.importorskip("psycopg2")

    class Coded(psycopg2.errors.UndefinedTable):
        pgcode = code  # a hand-built psycopg2 error has pgcode None; this stands in

    text = sanitize_error(_wrap(Coded(f'relation "{IDENT}" does not exist'), ProgrammingError))
    assert IDENT not in text
    assert word in text.lower()


def test_ac_46_06_a_real_missing_table_on_a_local_postgres_gives_no_identifier():
    engine = database.build_engine(
        "postgresql://foundryx:foundryx@localhost:5432/foundryx_service",
        connect_args={"connect_timeout": 2},
    )
    try:
        try:
            conn = engine.connect()
        except Exception:  # noqa: BLE001
            pytest.skip("no local postgres")
        with conn:
            with pytest.raises(ProgrammingError) as caught:
                conn.exec_driver_sql(f"SELECT * FROM {IDENT}_tbl")
        text = sanitize_error(caught.value)
        assert IDENT not in text and "table" in text.lower()
    finally:
        engine.dispose()


# ── 3. the detail goes to the server log ───────────────────────────────────


def test_ac_46_08_sanitize_error_logs_the_driver_exception(caplog):
    orig = OperationalError("SELECT 1", {}, Exception(f"detail {IDENT}"))
    with caplog.at_level(logging.DEBUG):
        sanitize_error(orig)
    assert any(
        r.exc_info and r.exc_info[1] is orig for r in caplog.records
    ), "a log record must carry the exception via exc_info"


# ── 4. a secret never rewrites a fixed sentence ────────────────────────────


@pytest.mark.parametrize(
    "secret,code,sentence",
    [
        ("database", "3D000", "_DATABASE_MISSING"),
        ("password", "28P01", "_LOGIN_REFUSED"),
        ("server", "08001", "_HOST_UNREACHABLE"),
    ],
)
def test_ac_46_06_a_secret_matching_a_word_leaves_the_sentence_unchanged(
    secret, code, sentence
):
    class Coded(Exception):
        pgcode = code

    text = sanitize_error(_wrap(Coded("x")), secrets=[secret])
    assert text == getattr(runtime, sentence)


# ── 5. the SQL source output names no constraint ───────────────────────────


def test_ac_46_06_the_sql_source_text_names_no_constraint_but_the_app_text_does():
    class Coded(Exception):
        pgcode = "23505"
        diag = SimpleNamespace(constraint_name="sample_name_key")

    exc = _wrap(Coded("x"), IntegrityError)
    assert "sample_name_key" not in sanitize_error(exc)
    assert "sample_name_key" in db_error_text(exc, "The record could not be saved")


# ── 6. the workflow update action ──────────────────────────────────────────

MARKER = "zz-placeholder-marker-9137"


def _app_db_error():
    class Coded(Exception):
        pgcode = "23505"

    return IntegrityError(
        "UPDATE t SET name=%(v)s", {"v": MARKER}, Coded(f"Key (name)=({MARKER}) exists")
    )


def _patch_update_action(monkeypatch):
    import app.workflow_engine.actions.entity_actions as actions

    def apply_update(*_a, **_k):
        raise _app_db_error()

    entity = SimpleNamespace(
        writable={"name"}, label="Sample", entity_type="sample", apply_update=apply_update
    )
    monkeypatch.setattr(
        actions, "_resolve_record", lambda *a, **k: (entity, SimpleNamespace(id="r1"))
    )


def _update_run(db):
    from app.models import DEFAULT_TENANT_ID
    from app.models.workflow import RUN_PENDING, Workflow, WorkflowRun

    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "n1", "kind": "action", "type": "entity.update",
             "config": {"entityType": "sample", "recordId": "r1",
                        "assignments": [{"field": "name", "value": "v"}]}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "trigger", "target": "n1"}],
    }
    workflow = Workflow(
        tenant_id=DEFAULT_TENANT_ID, name="Sample", description="", draft_definition_json=doc
    )
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID, workflow_id=workflow.id, status=RUN_PENDING,
        definition_snapshot_json=doc, trigger_payload_json={"triggeredBy": "manual"},
    )
    db.add(run)
    db.commit()
    return run


def test_ac_46_07_an_update_action_failure_stores_no_driver_message(session_factory, monkeypatch):
    from app.workflow_engine.executor import run_workflow

    db = session_factory()
    run = _update_run(db)
    _patch_update_action(monkeypatch)
    result = run_workflow(db, run.id)
    errors = [n.error for n in result.nodes if n.error]
    assert errors, "the update node must fail with an error"
    for error in errors:
        assert MARKER not in error
    assert MARKER not in (result.error or "")
    db.close()


def test_ac_46_07_an_update_action_failure_in_a_debug_rerun_returns_no_driver_message(
    session_factory, monkeypatch
):
    from app.workflow_engine.executor import debug_execute

    db = session_factory()
    run = _update_run(db)
    _patch_update_action(monkeypatch)
    touched = debug_execute(db, run, target_node_id="n1", scratch={}, stale_node_ids=[])
    failed = [t for t in touched if t.get("error")]
    assert failed
    for item in failed:
        assert MARKER not in item["error"]
    db.close()


# ── libpq phrases apply only to code-less psycopg2 connect failures ────────


def _coded(base_name, code, message):
    psycopg2 = pytest.importorskip("psycopg2")
    base = getattr(psycopg2.errors, base_name)

    class Coded(base):
        __module__ = "psycopg2.errors"  # the module a real psycopg2 error reports
        pgcode = code  # a hand-built psycopg2 error has pgcode None

    return Coded(message)


@pytest.mark.parametrize(
    "base,code,message",
    [
        ("InvalidTextRepresentation", "22P02", 'invalid input syntax for type integer: "sslx"'),
        ("UndefinedFunction", "42883", "function nosuchfn_46() does not exist"),
        ("UndefinedObject", "42704", 'type "nosuchtype_46" does not exist'),
    ],
)
def test_ac_46_06_a_coded_query_error_gets_the_code_text_not_a_connection_sentence(
    base, code, message
):
    text = sanitize_error(_wrap(_coded(base, code, message), ProgrammingError))
    assert code in text
    assert text not in (runtime._TLS_FAILED, runtime._DATABASE_MISSING)


@pytest.mark.parametrize(
    "message,expected",
    [
        ('connection to server at "127.0.0.1", port 5432 failed: FATAL:  '
         'database "classloader_46" does not exist\n', "_DATABASE_MISSING"),
        ('could not translate host name "ssl-db46.invalid" to address: '
         "nodename nor servname provided, or not known\n", "_HOST_UNREACHABLE"),
        ('connection to server at "127.0.0.1", port 5432 failed: FATAL:  '
         'role "norole_46" does not exist\n', "_LOGIN_REFUSED"),
        ('connection to server at "h", port 5432 failed: server does not support SSL, '
         "but SSL was required\n", "_TLS_FAILED"),
        ("SSL error: certificate verify failed\n", "_TLS_FAILED"),
        ('connection to server at "h", port 5432 failed: Connection refused\n',
         "_HOST_UNREACHABLE"),
        ('connection to server at "h", port 5432 failed: FATAL:  password authentication '
         'failed for user "u"\n', "_LOGIN_REFUSED"),
        ('connection to server at "h", port 5432 failed: FATAL:  database "x" does not '
         "exist\n", "_DATABASE_MISSING"),
    ],
)
def test_ac_46_06_a_codeless_connect_failure_maps_by_libpq_phrase_only(message, expected):
    assert sanitize_error(_wrap(_pg(message))) == getattr(runtime, expected)


# ── the app text accepts only a well-formed SQLSTATE ───────────────────────


@pytest.mark.parametrize("bad", ["X" * 64, f"{MARKER}", "abcde", "2350", "235055"])
def test_ac_46_05_a_malformed_pgcode_is_left_out_of_the_text(bad):
    class Coded(Exception):
        pgcode = bad

    text = db_error_text(_wrap(Coded("x"), IntegrityError), "The record could not be saved")
    assert MARKER not in text
    assert "code" not in text
    assert bad not in text


def test_ac_46_05_a_well_formed_pgcode_is_kept():
    class Coded(Exception):
        pgcode = "23505"

    text = db_error_text(_wrap(Coded("x"), IntegrityError), "The record could not be saved")
    assert "code 23505" in text
