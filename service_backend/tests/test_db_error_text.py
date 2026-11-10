"""Plan 46 (AC-46-05): one helper turns a database error into fixed text.

The text holds the caller's sentence, the error class, and when the driver
supplies them the error code and the constraint name. It never holds the
driver's message, a statement literal or a bound value.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

MARKER = "zz-placeholder-marker-9137"
WHAT = "The record could not be saved"


def _helper():
    from app.db_errors import db_error_text

    return db_error_text


class PgLikeError(Exception):
    """Shaped like a psycopg2 error: pgcode, diag.constraint_name, long text."""

    def __init__(self, pgcode, constraint):
        self.pgcode = pgcode
        self.diag = SimpleNamespace(constraint_name=constraint)
        super().__init__(
            "duplicate key value violates unique constraint\n"
            f"DETAIL:  Key (name)=({MARKER}) already exists.\n"
            f"Failing row contains ({MARKER}, 12).\n"
            f"LINE 1: INSERT INTO sample_table (name) VALUES ('{MARKER}')\n"
        )


class MssqlLikeError(Exception):
    """Shaped like a pymssql error: args[0] is the server error number."""

    def __init__(self, number):
        super().__init__(
            number,
            f"Violation of UNIQUE KEY constraint. The duplicate key value is ({MARKER})."
            .encode(),
        )


class MysqlLikeError(Exception):
    """Shaped like a pymysql error: args[0] is the server error number."""

    def __init__(self, number):
        super().__init__(number, f"Duplicate entry '{MARKER}' for key 'sample_name_key'")


def _wrap(cls, orig):
    return cls("INSERT INTO sample_table (name) VALUES (%(v)s)", {"v": MARKER}, orig)


def test_ac_46_05_a_postgres_error_gives_sentence_class_code_and_constraint():
    exc = _wrap(IntegrityError, PgLikeError("23505", "sample_name_key"))
    text = _helper()(exc, WHAT)
    assert WHAT in text
    assert "IntegrityError" in text
    assert "23505" in text
    assert "sample_name_key" in text
    assert MARKER not in text
    assert "DETAIL" not in text and "INSERT INTO" not in text


def test_ac_46_05_a_postgres_error_without_a_constraint_omits_it():
    exc = _wrap(DataError, PgLikeError("22001", None))
    text = _helper()(exc, WHAT)
    assert WHAT in text and "DataError" in text and "22001" in text
    assert MARKER not in text
    assert "None" not in text


def test_ac_46_05_a_sql_server_error_gives_sentence_class_and_number():
    exc = _wrap(IntegrityError, MssqlLikeError(2627))
    text = _helper()(exc, WHAT)
    assert WHAT in text
    assert "IntegrityError" in text
    assert "2627" in text
    assert MARKER not in text


def test_ac_46_05_a_mysql_error_gives_sentence_class_and_number():
    exc = _wrap(IntegrityError, MysqlLikeError(1062))
    text = _helper()(exc, WHAT)
    assert WHAT in text
    assert "IntegrityError" in text
    assert "1062" in text
    assert MARKER not in text


def test_ac_46_05_an_operational_error_keeps_the_text_free_of_driver_words():
    exc = _wrap(OperationalError, PgLikeError("08006", None))
    text = _helper()(exc, WHAT)
    assert WHAT in text and "OperationalError" in text and "08006" in text
    assert MARKER not in text


def test_ac_46_05_an_error_with_no_driver_part_still_gives_sentence_and_class():
    text = _helper()(ValueError(f"bad value {MARKER}"), WHAT)
    assert WHAT in text
    assert "ValueError" in text
    assert MARKER not in text


def test_ac_46_05_a_real_pymysql_error_object_is_covered():
    pymysql = pytest.importorskip("pymysql")
    orig = pymysql.err.IntegrityError(1062, f"Duplicate entry '{MARKER}' for key 'k'")
    text = _helper()(_wrap(IntegrityError, orig), WHAT)
    assert "1062" in text and WHAT in text
    assert MARKER not in text


def test_ac_46_05_a_real_psycopg2_error_object_is_covered():
    errors = pytest.importorskip("psycopg2.errors")
    orig = errors.UniqueViolation(f"duplicate key\nDETAIL:  Key (name)=({MARKER}) exists.")
    text = _helper()(_wrap(IntegrityError, orig), WHAT)
    assert WHAT in text and "IntegrityError" in text
    assert MARKER not in text
