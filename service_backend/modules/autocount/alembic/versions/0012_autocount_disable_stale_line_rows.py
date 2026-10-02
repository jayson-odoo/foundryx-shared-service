"""autocount disable stale line rows (code-review round R1)

0011's backfill (before R1's fix) seeded every ``mapping.DOCUMENT_LINE_
FIXED_FIELDS`` row ``is_enabled=True`` regardless of whether its
``source_path`` actually matched the task's saved ``line_result_columns`` -
so the S1 preview-column gate rejected the operator's very first
Mapping-tab save on any task 0011 had already touched (live task
48e2b593 - "'discount' is not among the line query's last preview
columns").

This migration REPAIRS every already-migrated task in place by re-running
``backfill.disable_line_rows_missing_from_preview`` - the same function the
S1 gate itself now agrees with - which flips an ENABLED line row whose
``source_path`` is not among the task's ``line_result_columns`` to
``is_enabled=False`` (idempotent; a never-previewed task is left alone
entirely, since it has nothing to check against yet).

Same two-connection discipline as 0010/0011's own docstrings: this
migration alters no schema, so a session sharing Alembic's own bind is
safe (one flush at the end per task, Alembic owns the single commit).

Revision ID: 0012_autocount_disable_stale   (28 chars <= 32)
Revises: 0011_autocount_doc_line_fix
Create Date: 2026-09-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from modules.autocount.backfill import disable_line_rows_missing_from_preview
from modules.autocount.canonical.documents import DOCUMENT_ENTITY_TYPES

revision: str = "0012_autocount_disable_stale"
down_revision: Union[str, Sequence[str], None] = "0011_autocount_doc_line_fix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    rows = bind.execute(
        sa.text(
            f'SELECT tenant_id, company_id, entity_type FROM "{SCHEMA}".ac_entity_config '
            f"WHERE entity_type = ANY(:entity_types)"
        ),
        {"entity_types": list(DOCUMENT_ENTITY_TYPES)},
    ).fetchall()

    if not rows:
        return

    session = Session(bind=bind)
    try:
        for tenant_id, company_id, entity_type in rows:
            disable_line_rows_missing_from_preview(session, tenant_id, company_id, entity_type)
        session.flush()
    finally:
        session.close()


def downgrade() -> None:
    # A disabled row is still an ordinary, editable ac_field_mapping row -
    # the operator (or a re-preview) can re-enable it. Nothing to reverse,
    # same stance as 0010/0011.
    pass
