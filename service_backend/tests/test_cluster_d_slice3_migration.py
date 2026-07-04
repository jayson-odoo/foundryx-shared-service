"""Cluster D slice-3 — migration regression (tester-authored, BUG GUARD).

BUG FOUND IN QA (sprint-4/05 slice 3): the slice-3 EMS migration revision id
``0005_cluster_d_ticket_status_checkpoints`` is 40 characters, but Alembic's
``alembic_version`` (here ``alembic_version_ems``) ``version_num`` column is
``VARCHAR(32)`` (Alembic's ``MAX_REVISION_LENGTH``). On Postgres,
``run_module_migrations('ems')`` therefore fails at the version-stamp UPDATE:

    psycopg2.errors.StringDataRightTruncation:
        value too long for type character varying(32)

Consequence: the slice-3 columns (``tickets.qr_nonce`` / ``tickets.status_id``)
+ the checkpoints tables never apply on a real Postgres deployment; the public
GA/RESERVED checkout + every slice-3 flow 500s ("column tickets.qr_nonce does
not exist"). The full pytest suite is GREEN only because conftest builds the
schema via ``create_all`` (no Alembic) — so the broken migration is invisible to
the existing tests.

These tests were written to FAIL until the coder shortened the revision id (and
backfills the live DB). FIXED (coder, sprint-4/05 slice 3): the revision id was
renamed ``0005_cluster_d_ticket_status_checkpoints`` → ``0005_ticket_status_
checkpoints`` (30 chars), so the xfail markers were removed and these now PASS as
permanent regression guards. Mapped to: Cluster D slice-3 ticket status entity +
checkpoints (the migration that ships them) and the cross-branch-alembic deploy
lesson in CLAUDE.md.
"""
import re
from pathlib import Path

# Alembic's hard limit on a revision id stored in alembic_version.version_num.
ALEMBIC_MAX_REVISION_LENGTH = 32

_MIGRATIONS_ROOT = Path(__file__).resolve().parent.parent / "modules"


def _revision_ids():
    """(module, file, revision_id) for every module migration on disk."""
    out = []
    rev_re = re.compile(r"""^revision(?:\s*:\s*str)?\s*=\s*['"]([^'"]+)['"]""", re.M)
    for vfile in sorted(_MIGRATIONS_ROOT.glob("*/alembic/versions/*.py")):
        if vfile.name.startswith("__"):
            continue
        text = vfile.read_text()
        m = rev_re.search(text)
        if m:
            module = vfile.parts[vfile.parts.index("modules") + 1]
            out.append((module, vfile.name, m.group(1)))
    return out


def test_module_migration_revision_ids_fit_alembic_column():
    """Every module migration revision id must fit Alembic's VARCHAR(32) version
    column — else `run_module_migrations` 500s at stamp time on Postgres.

    FIXED: the slice-3 EMS migration id was shortened to
    `0005_ticket_status_checkpoints` (30 chars). Permanent regression guard."""
    too_long = [
        (mod, fname, rid, len(rid))
        for (mod, fname, rid) in _revision_ids()
        if len(rid) > ALEMBIC_MAX_REVISION_LENGTH
    ]
    assert not too_long, (
        "Module migration revision ids exceed Alembic's VARCHAR(32) version "
        f"column (un-runnable on Postgres): {too_long}"
    )


def test_slice3_ems_migration_id_specifically_fits():
    """Pinpoint the slice-3 migration so the guard is explicit: its revision id
    (read FROM DISK, not hard-coded) must fit Alembic's VARCHAR(32) column.

    FIXED: renamed `0005_cluster_d_ticket_status_checkpoints` (40) →
    `0005_ticket_status_checkpoints` (30)."""
    slice3 = [
        (mod, fname, rid)
        for (mod, fname, rid) in _revision_ids()
        if mod == "ems" and fname.startswith("0005_")
    ]
    assert slice3, "slice-3 EMS migration (0005_*) not found on disk"
    for mod, fname, rid in slice3:
        assert len(rid) <= ALEMBIC_MAX_REVISION_LENGTH, (
            f"slice-3 EMS migration id {rid!r} ({fname}) is {len(rid)} chars "
            f"(> {ALEMBIC_MAX_REVISION_LENGTH}); Postgres stamp UPDATE fails with "
            "StringDataRightTruncation — the slice-3 columns/tables never apply."
        )
