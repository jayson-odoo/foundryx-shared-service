"""Sprint-5/11 S4 - AC-11-72: module Alembic ``0022_autocount_preview_job``
adds the single nullable ``ac_entity_config.preview_job_id`` column, chains
onto ``0021_autocount_pull_gateway``, and stays a single head.

RED before the coder: no ``0022_*`` file exists under
``modules/autocount/alembic/versions/`` yet.

Pattern mirrors ``test_autocount_spo_container_number.py``'s own
``test_revision_0016_chains_onto_0015...`` (static file inspection - the
pytest rig uses ``create_all``, which cannot see migrations at all, so this
file never touches the DB).
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import modules.autocount as autocount_module

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
PREVIOUS_REVISION = "0021_autocount_pull_gateway"


def test_revision_0022_adds_the_single_preview_job_claim_column():
    candidates = sorted(VERSIONS_DIR.glob("0022_*.py"))
    assert candidates, "no 0022_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()

    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32, "revision id missing or > 32 chars"

    spec = importlib.util.spec_from_file_location("_ac_rev_0022", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION, module.down_revision

    assert "preview_job_id" in text, f"{path.name} does not mention preview_job_id"

    # Single head: no sibling revision may also chain onto 0021.
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), (
            f"{other.name} also chains onto {PREVIOUS_REVISION}"
        )


def test_ac_entity_config_model_carries_the_preview_job_id_column():
    """The ORM side of the same column - the ``create_all`` test rig picks
    this up directly (migrations are invisible to pytest), so the model
    column is what every OTHER test in this batch actually exercises."""
    from modules.autocount.models import AcEntityConfig

    assert hasattr(AcEntityConfig, "preview_job_id"), (
        "AcEntityConfig has no preview_job_id column - the S4 claim (AC-11-23) "
        "has nowhere to live"
    )
    column = AcEntityConfig.__table__.c.preview_job_id
    assert column.nullable is True, "every existing row must read NULL - no backfill needed"
