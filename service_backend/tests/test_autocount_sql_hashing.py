"""Row-hash normalisation matrix (plan 22 §2.2 ``hashing.py``, AC-22-16).

The hash is the ONLY thing reconcile stores about a source row, so its
normalisation is load-bearing in both directions:

* too STRICT (a driver decoding ``1`` as ``int`` here and ``Decimal('1')``
  there) stages an update on every single run forever - the "everything
  changed" failure that makes reconcile useless and hammers the consumer;
* too LOOSE (``None`` colliding with ``''``, ``True`` colliding with ``1``)
  silently swallows a real change - the failure nobody ever notices.

So the matrix below pins BOTH edges explicitly.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from modules.autocount.sql_source.hashing import compared_columns_for, row_hash


def h(row, columns):
    return row_hash(row, columns)


# ── column selection ─────────────────────────────────────────────────────────


def test_only_the_compared_columns_move_the_hash():
    """"On change of which field" is the whole point (AC-22-16): a column that
    is NOT compared must never stage an update."""
    a = {"code": "C1", "name": "Acme", "internal_note": "one"}
    b = {"code": "C1", "name": "Acme", "internal_note": "two"}
    assert h(a, ["code", "name"]) == h(b, ["code", "name"])
    assert h(a, ["code", "name", "internal_note"]) != h(
        b, ["code", "name", "internal_note"]
    )


def test_column_order_does_not_change_the_hash():
    """The compared set is a SET; a config edit that reorders it must not
    invalidate every stored hash."""
    row = {"code": "C1", "name": "Acme"}
    assert h(row, ["code", "name"]) == h(row, ["name", "code"])


def test_a_missing_column_hashes_like_an_explicit_null():
    """A query that stops selecting a column and one that returns NULL are the
    same absence - never a spurious update."""
    assert h({"code": "C1"}, ["code", "name"]) == h(
        {"code": "C1", "name": None}, ["code", "name"]
    )


def test_the_column_name_is_part_of_the_hash():
    """Values alone would collide across a rename/swap."""
    assert h({"a": "1", "b": "2"}, ["a", "b"]) != h({"a": "2", "b": "1"}, ["a", "b"])


# ── value normalisation: the "too strict" edge (must be EQUAL) ───────────────


def test_numeric_decodings_of_the_same_value_agree():
    """psycopg2 hands back ``Decimal``, sqlite3 an ``int``/``float``, pymysql
    either - the same money must not read as a change per dialect."""
    base = h({"n": Decimal("1.50")}, ["n"])
    assert h({"n": Decimal("1.5")}, ["n"]) == base
    assert h({"n": 1.5}, ["n"]) == base
    base_int = h({"n": 1}, ["n"])
    assert h({"n": Decimal("1")}, ["n"]) == base_int
    assert h({"n": Decimal("1.000")}, ["n"]) == base_int
    assert h({"n": 1.0}, ["n"]) == base_int


def test_the_same_instant_hashes_the_same_however_it_is_zoned():
    """A driver returning naive-UTC and one returning aware must agree."""
    aware = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 8, 30, 9, 0)
    other_zone = datetime(2026, 8, 30, 17, 0, tzinfo=timezone(timedelta(hours=8)))
    assert h({"t": naive}, ["t"]) == h({"t": aware}, ["t"])
    assert h({"t": other_zone}, ["t"]) == h({"t": aware}, ["t"])


def test_bytes_hash_by_content():
    assert h({"b": b"\x00\x01"}, ["b"]) == h({"b": bytearray(b"\x00\x01")}, ["b"])


# ── value normalisation: the "too loose" edge (must DIFFER) ─────────────────


def test_null_is_not_an_empty_string_and_not_a_zero():
    """The classic silent-swallow: a cleared field reading as unchanged."""
    assert h({"v": None}, ["v"]) != h({"v": ""}, ["v"])
    assert h({"v": None}, ["v"]) != h({"v": 0}, ["v"])
    assert h({"v": ""}, ["v"]) != h({"v": 0}, ["v"])


def test_booleans_never_collide_with_their_numeric_twins():
    """MySQL hands ``is_active`` back as ``1``/``0``, Postgres as a bool - but
    ``True`` must not collide with the STRING ``'1'`` either."""
    assert h({"v": True}, ["v"]) != h({"v": "1"}, ["v"])
    assert h({"v": False}, ["v"]) != h({"v": "0"}, ["v"])
    assert h({"v": True}, ["v"]) != h({"v": False}, ["v"])


def test_a_number_and_its_string_form_differ():
    assert h({"v": 1}, ["v"]) != h({"v": "1"}, ["v"])


def test_a_date_a_time_and_a_datetime_never_collide():
    assert h({"v": date(2026, 8, 30)}, ["v"]) != h(
        {"v": datetime(2026, 8, 30)}, ["v"]
    )
    assert h({"v": time(9, 0)}, ["v"]) != h({"v": "09:00:00"}, ["v"])


def test_the_hash_is_a_stable_hex_digest():
    """Stored in a String column and compared as text - never a Python hash
    (salted per process, so every restart would restage the world)."""
    value = h({"code": "C1"}, ["code"])
    assert isinstance(value, str) and len(value) == 64
    assert value == h({"code": "C1"}, ["code"])
    assert int(value, 16) >= 0  # hex


# ── compared-column defaulting (AC-22-11) ───────────────────────────────────


def test_compared_columns_default_to_every_result_column_minus_the_keys():
    assert compared_columns_for(
        configured=[], result_columns=["acc_no", "name", "email"], key_columns=["acc_no"]
    ) == ["email", "name"]


def test_configured_compared_columns_win_and_never_include_a_key():
    assert compared_columns_for(
        configured=["name", "acc_no"],
        result_columns=["acc_no", "name", "email"],
        key_columns=["acc_no"],
    ) == ["name"]


def test_compared_columns_ignore_a_pick_the_query_no_longer_returns():
    """The query was edited after the picks were saved: hashing a column that
    does not exist would hash NULL for every row and blind the diff."""
    assert compared_columns_for(
        configured=["name", "gone"],
        result_columns=["acc_no", "name"],
        key_columns=["acc_no"],
    ) == ["name"]
