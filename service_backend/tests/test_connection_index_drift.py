"""Drift guard: the LAST migration that rebuilds ``uq_connection_tenant_type``
must carry the model's ``EXEMPT_FROM_ONE_PER_TYPE`` predicate.

The create_all pytest suite builds the index from the ORM model, so a migration
that rebuilds it with a stale predicate (``ai_core_s1b_ai_subsystem`` dropped
``erp`` while adding ``llm``) passes CI and breaks every real deploy. This test
walks the Alembic chain from head and checks the newest rebuild.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.connection import EXEMPT_FROM_ONE_PER_TYPE

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
_INDEX = "uq_connection_tenant_type"
_PREDICATE = re.compile(r"type\s+NOT\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def _upgrade_body(source: str) -> str:
    """The ``upgrade()`` body only - a docstring that NARRATES an old predicate
    must not be mistaken for the one the migration applies."""
    start = source.index("def upgrade()")
    end = source.find("def downgrade()", start)
    return source[start : end if end != -1 else None]


def test_last_rebuild_of_uq_connection_tenant_type_matches_model_predicate():
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single head, got {heads}"

    # Walk head -> base; the FIRST hit is the newest rebuild.
    for rev in script.walk_revisions(base="base", head=heads[0]):
        source = Path(rev.path).read_text()
        body = _upgrade_body(source)
        if f'"{_INDEX}"' not in body:
            continue
        match = _PREDICATE.search(body)
        assert match, f"{rev.revision} rebuilds {_INDEX} without a NOT IN predicate"
        found = {p.strip().strip("'\"") for p in match.group(1).split(",")}
        assert found == set(EXEMPT_FROM_ONE_PER_TYPE), (
            f"{rev.revision} rebuilds {_INDEX} with {sorted(found)}; the model "
            f"exempts {sorted(EXEMPT_FROM_ONE_PER_TYPE)}"
        )
        return
    raise AssertionError(f"no migration rebuilds {_INDEX}")
