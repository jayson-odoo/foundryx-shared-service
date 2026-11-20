"""Plan 47 review round: a database error is found behind a wrapper (cause or
context), the walk ends on a cycle, and the detail goes to the server log."""
import logging
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.db_errors import db_error_in, stored_error_text

MARKER = "zzmarker4748"


class PgLikeError(Exception):
    def __init__(self):
        self.pgcode = "23505"
        self.diag = SimpleNamespace(constraint_name=None)
        super().__init__(f"server said no\nDETAIL:  Key (name)=({MARKER}) exists.\n")


def _db_error():
    return IntegrityError("INSERT INTO t (name) VALUES (%(v)s)", {"v": MARKER}, PgLikeError())


def _fixed(text):
    assert MARKER not in text
    assert "IntegrityError" in text and "23505" in text, text


def test_a_database_error_is_found_through_the_cause():
    try:
        try:
            raise _db_error()
        except IntegrityError as inner:
            raise RuntimeError(f"wrapped: {inner}") from inner
    except RuntimeError as wrapper:
        assert db_error_in(wrapper) is wrapper.__cause__
        _fixed(stored_error_text(wrapper, "Step failed"))


def test_a_database_error_is_found_through_the_context():
    try:
        try:
            raise _db_error()
        except IntegrityError as inner:
            raise RuntimeError(f"wrapped: {inner}")
    except RuntimeError as wrapper:
        assert wrapper.__cause__ is None
        assert db_error_in(wrapper) is wrapper.__context__
        _fixed(stored_error_text(wrapper, "Step failed"))


def test_a_database_error_is_found_behind_a_suppressed_cause():
    try:
        try:
            raise _db_error()
        except IntegrityError as inner:
            raise RuntimeError(f"wrapped: {inner}") from None
    except RuntimeError as wrapper:
        assert wrapper.__suppress_context__ is True
        _fixed(stored_error_text(wrapper, "Step failed"))


def test_a_cause_cycle_ends_with_no_database_error():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    assert db_error_in(a) is None
    a.__cause__, b.__cause__ = None, None
    a.__context__, b.__context__ = b, a
    assert db_error_in(a) is None


def test_an_unrelated_chain_keeps_its_text():
    try:
        try:
            raise ValueError("inner note")
        except ValueError as inner:
            raise RuntimeError("outer note") from inner
    except RuntimeError as wrapper:
        assert db_error_in(wrapper) is None
        assert stored_error_text(wrapper, "Step failed") == "Step failed: outer note"


def _logged_db_error(caplog):
    return [
        r for r in caplog.records
        if r.exc_info and isinstance(r.exc_info[1], IntegrityError)
    ]


def test_describe_consumer_failure_logs_the_database_error(caplog):
    from modules.autocount.sinks_sorento import describe_consumer_failure

    with caplog.at_level(logging.DEBUG):
        line, _status, detail = describe_consumer_failure(_db_error(), sink=None)
    assert MARKER not in line and MARKER not in detail
    assert _logged_db_error(caplog), "the database error must reach the log with exc_info"


def test_the_doc_feed_sink_failure_text_logs_the_database_error(caplog):
    from modules.autocount.doc_feed.runner import _sink_failure_text

    with caplog.at_level(logging.DEBUG):
        line = _sink_failure_text(_db_error(), None)
    assert MARKER not in line
    assert _logged_db_error(caplog), "the database error must reach the log with exc_info"
