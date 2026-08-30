"""SELECT-only static guard (AC-22-03) - deny-first.

The ONLY statement shape that passes is exactly one ``SELECT`` (or
``WITH ... SELECT``). Everything else is rejected here, before a connection is
even opened. The rules, in order:

1. Comments are stripped (``--`` and ``/* */``) so nothing can hide behind them.
2. ONE trailing ``;`` is tolerated (people type it); any other ``;`` outside a
   string literal / quoted identifier means a second statement → rejected.
3. The first token must be ``SELECT`` or ``WITH``.
4. No token anywhere may be a DML/DDL/execution keyword (``INSERT``,
   ``UPDATE``, ``DELETE``, ``DROP``, ``EXEC``, ``INTO``, ...) or a function
   that reads the file system, sleeps, or reaches another session/process
   (``pg_read_file``, ``LOAD_FILE``, ``pg_sleep``, ``SLEEP``, ``dblink``,
   ``xp_*``, ...). Tokens are whole identifiers, matched case-insensitively;
   a schema prefix is a separate token so ``pg_catalog.pg_read_file`` is
   caught while ``into_qty`` is not. String literals and quoted identifiers
   are scrubbed first, so ``WHERE note = 'DROP TABLE'``, ``LIKE '%sleep%'``
   and ``SELECT [Update]`` are fine while ``SELECT ... INTO`` and ``FOR
   UPDATE`` are not.

Deny-first means a legitimate but unusual SELECT can be refused (a bare column
named ``copy``, ``do`` or ``sleep``, a ``;`` inside a literal). That is the
accepted trade: quote the identifier, and never store the literal. The guard is
NOT the only line of defence - the session is read-only where the dialect
supports it, every transaction is rolled back, and the login should be
read-only too.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from .errors import SqlGuardError

__all__ = [
    "assert_select_only",
    "mask_quoted",
    "normalize_statement",
    "top_level_words",
    "SqlGuardError",
]

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
        "XP_REGREAD",
        "XP_DIRTREE",
        "XP_FILEEXIST",
        "SP_OACREATE",
        "SP_OAMETHOD",
        # file system / large objects / out-of-process reach (S1 review). A
        # plain SELECT can call these; the token match is on the bare
        # identifier so a schema-qualified ``pg_catalog.pg_read_file`` is
        # caught too (the tokeniser splits on ``.``).
        "PG_READ_FILE",
        "PG_READ_BINARY_FILE",
        "PG_LS_DIR",
        "PG_STAT_FILE",
        "LO_IMPORT",
        "LO_EXPORT",
        "LO_GET",
        "LOAD_FILE",
        "OUTFILE",
        "DUMPFILE",
        "DBLINK",
        "DBLINK_CONNECT",
        # sleep / DoS / other sessions
        "PG_SLEEP",
        "PG_SLEEP_FOR",
        "PG_SLEEP_UNTIL",
        "SLEEP",
        "BENCHMARK",
        "PG_TERMINATE_BACKEND",
        "PG_CANCEL_BACKEND",
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


def _blank(match: "re.Match[str]") -> str:
    return " " * len(match.group(0))


_WORD_OR_PAREN = re.compile(r"[A-Za-z_][A-Za-z0-9_$#@]*|\(|\)")


def top_level_words(statement: str) -> List[Tuple[str, int, int]]:
    """``(UPPER_WORD, start, end)`` for every identifier at parenthesis depth
    0 of ``statement`` - literals and quoted identifiers masked first, so
    offsets apply to the ORIGINAL text. Depth-0 means "a clause of the
    OUTERMOST statement, never a CTE body or a subquery's own clause".

    Shared by the preview row-cap rewriter (``preview.wrap_preview``) and the
    DB-source incremental-fetch statement builder (``source.py`` - stripping
    a meaningless trailing ``ORDER BY`` before the derived-table wrap, S2
    review BLOCKER 2). One tokeniser, not two copies drifting apart.
    """
    words: List[Tuple[str, int, int]] = []
    depth = 0
    for match in _WORD_OR_PAREN.finditer(mask_quoted(statement)):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            words.append((token.upper(), match.start(), match.end()))
    return words


def mask_quoted(text: str) -> str:
    """``text`` with every string literal and quoted identifier replaced by
    the SAME number of spaces - positions are preserved, so an offset found
    in the masked text can be applied to the original (the preview rewriter
    relies on that)."""
    return _QUOTED_IDENT.sub(_blank, _STRING_LITERAL.sub(_blank, text))


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

    scrubbed = mask_quoted(text)
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
