"""SELECT-only static guard (AC-22-03) - deny-first.

The ONLY statement shape that passes is exactly one ``SELECT`` (or
``WITH ... SELECT``). Everything else is rejected here, before a connection is
even opened. The rules, in order:

1. Comments are stripped (``--`` and ``/* */``) so nothing can hide behind them.
2. ONE trailing ``;`` is tolerated (people type it); any other ``;`` outside a
   string literal / quoted identifier means a second statement → rejected.
3. The first token must be ``SELECT`` or ``WITH``.
4. No token anywhere may be a DML/DDL/execution keyword (``INSERT``,
   ``UPDATE``, ``DELETE``, ``DROP``, ``EXEC``, ``INTO``, ...). String literals
   and quoted identifiers are scrubbed first, so ``WHERE note = 'DROP TABLE'``
   and ``SELECT [Update]`` are fine while ``SELECT ... INTO`` and ``FOR UPDATE``
   are not.

Deny-first means a legitimate but unusual SELECT can be refused (a bare column
named ``copy``, a ``;`` inside a literal). That is the accepted trade: quote the
identifier, and never store the literal. The guard is NOT the only line of
defence - the session is read-only where the dialect supports it, every
transaction is rolled back, and the login should be read-only too.
"""
from __future__ import annotations

import re

from .errors import SqlGuardError

__all__ = ["assert_select_only", "normalize_statement", "SqlGuardError"]

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
# A single-quoted literal with '' escapes; double-quoted / [bracketed] /
# `backticked` identifiers. Replaced with a space before tokenising.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"|\[[^\]]*\]|`[^`]*`')
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$#@]*")

_START_TOKENS = frozenset({"SELECT", "WITH"})

# Anything that writes, defines, executes, locks, or reaches outside the
# database. A token match ANYWHERE (outside literals/quoted identifiers)
# rejects the statement. Deliberately generous - deny-first.
_FORBIDDEN_TOKENS = frozenset(
    {
        # DML
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "UPSERT",
        "TRUNCATE",
        "INTO",
        "LOAD",
        "COPY",
        "IMPORT",
        "BULK",
        # DDL
        "CREATE",
        "ALTER",
        "DROP",
        "RENAME",
        "REINDEX",
        "VACUUM",
        "ANALYZE",
        "CLUSTER",
        "REFRESH",
        # execution / procedures / dynamic SQL
        "EXEC",
        "EXECUTE",
        "CALL",
        "DO",
        "PREPARE",
        "DEALLOCATE",
        "DECLARE",
        "SP_EXECUTESQL",
        "XP_CMDSHELL",
        "OPENROWSET",
        "OPENQUERY",
        "OPENDATASOURCE",
        "DBCC",
        "BACKUP",
        "RESTORE",
        "SHUTDOWN",
        "KILL",
        "RECONFIGURE",
        "WAITFOR",
        # grants / sessions / transactions / locks
        "GRANT",
        "REVOKE",
        "DENY",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "LOCK",
        "UNLOCK",
        "USE",
        "LISTEN",
        "NOTIFY",
        "DISCARD",
        "ATTACH",
        "DETACH",
        "PRAGMA",
        "HANDLER",
        "INSTALL",
        "UNINSTALL",
    }
)

_ONLY_ONE = "Only a single SELECT statement is allowed."
_EMPTY = "Enter a SELECT statement."


def _strip_comments(sql: str) -> str:
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql))


def normalize_statement(sql: str) -> str:
    """The statement as STORED: outer whitespace and ONE trailing ``;`` removed,
    comments kept (they are the operator's text). Does not validate."""
    text = (sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def assert_select_only(sql: str) -> str:
    """Validate + return the EXECUTABLE form of ``sql`` (comments stripped, one
    trailing ``;`` removed, outer whitespace trimmed).

    Raises ``SqlGuardError`` (an operator-safe message) for anything that is
    not exactly one SELECT / WITH...SELECT statement.
    """
    text = _strip_comments(sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise SqlGuardError(_EMPTY)

    scrubbed = _QUOTED_IDENT.sub(" ", _STRING_LITERAL.sub(" ", text))
    if ";" in scrubbed:
        raise SqlGuardError(_ONLY_ONE)

    tokens = [t.upper() for t in _TOKEN.findall(scrubbed)]
    if not tokens or tokens[0] not in _START_TOKENS:
        raise SqlGuardError(_ONLY_ONE)
    if tokens[0] == "WITH" and "SELECT" not in tokens:
        raise SqlGuardError(_ONLY_ONE)

    forbidden = next((t for t in tokens if t in _FORBIDDEN_TOKENS), None)
    if forbidden is not None:
        raise SqlGuardError(
            f"Only a single SELECT statement is allowed - '{forbidden}' is not permitted."
        )
    return text
