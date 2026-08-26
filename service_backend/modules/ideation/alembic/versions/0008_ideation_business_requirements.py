"""ideation - Business Requirement entity (Phase B-i slice 2, AC-BI-15..19).

Create ``app_ideation.business_requirements`` (+ the Idea↔BR many-many join) and
the versioned artifact-template store (``ideation_artifact_templates`` +
``ideation_artifact_template_versions``). Refs to core (tenant/product/status/
users) are plain indexed columns, not DB FKs (BL-030); intra-schema FKs (join →
ideas/BRs; version → template) are kept.

CRITICAL (same deploy lesson as 0005/0007): idempotent
(``CREATE TABLE IF NOT EXISTS``) AND the same tables land via
``IdeationBase.metadata.create_all`` in the module's ``install()`` - a fresh
install gets the tables whether the stamp-path or the upgrade-path runs.
Postgres-only DDL; a no-op on the SQLite test engine (the test suite creates the
tables via ``create_all``). ``TIMESTAMPTZ`` for ``UTCDateTime``, ``JSONB`` for
``JSON``, explicit ``CREATE INDEX IF NOT EXISTS``.

Revision ID: 0008_ideation_business_reqs
Revises: 0007_ideation_idea_attachments
Create Date: 2026-07-22
"""
from alembic import op
from sqlalchemy import text

# ≤ 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0008_ideation_business_reqs"
down_revision = "0007_ideation_idea_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    # ── artifact templates (versioned form_engine docs) ──────────────────────
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".ideation_artifact_templates ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NULL,"
            "  template_key VARCHAR NOT NULL,"
            "  name VARCHAR NOT NULL,"
            "  description TEXT NOT NULL DEFAULT '',"
            "  active_version_id VARCHAR NULL,"
            "  is_system BOOLEAN NOT NULL DEFAULT false,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_tenant '
            f'ON "{s}".ideation_artifact_templates (tenant_id)'
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_key '
            f'ON "{s}".ideation_artifact_templates (template_key)'
        )
    )
    # Partial unique per tier (BL-065 lesson).
    bind.execute(
        text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_ideation_artifact_tmpl_tenant_key '
            f'ON "{s}".ideation_artifact_templates (tenant_id, template_key) '
            "WHERE tenant_id IS NOT NULL"
        )
    )
    bind.execute(
        text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_ideation_artifact_tmpl_platform_key '
            f'ON "{s}".ideation_artifact_templates (template_key) '
            "WHERE tenant_id IS NULL"
        )
    )

    # ── immutable template versions ──────────────────────────────────────────
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".ideation_artifact_template_versions ('
            "  id VARCHAR PRIMARY KEY,"
            f'  template_id VARCHAR NOT NULL REFERENCES "{s}".ideation_artifact_templates(id),'
            "  tenant_id VARCHAR NULL,"
            "  version INTEGER NOT NULL,"
            "  doc_json JSONB NOT NULL,"
            "  created_by VARCHAR NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_ideation_artifact_tmpl_ver UNIQUE (template_id, version)"
            ")"
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_ver_template '
            f'ON "{s}".ideation_artifact_template_versions (template_id)'
        )
    )
    bind.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_ver_tenant '
            f'ON "{s}".ideation_artifact_template_versions (tenant_id)'
        )
    )

    # ── business requirements ────────────────────────────────────────────────
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".business_requirements ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            "  product_id VARCHAR NOT NULL,"
            "  status_id VARCHAR NOT NULL,"
            "  template_key VARCHAR NOT NULL,"
            "  template_version INTEGER NOT NULL,"
            "  title VARCHAR NOT NULL DEFAULT '',"
            "  answers_json JSONB NULL,"
            "  created_by VARCHAR NULL,"
            "  updated_by VARCHAR NULL,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    for col in ("tenant_id", "product_id", "status_id", "created_by", "updated_by"):
        bind.execute(
            text(
                f'CREATE INDEX IF NOT EXISTS ix_business_requirements_{col} '
                f'ON "{s}".business_requirements ({col})'
            )
        )

    # ── Idea ↔ BR many-many join ─────────────────────────────────────────────
    bind.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{s}".idea_business_requirements ('
            "  id VARCHAR PRIMARY KEY,"
            "  tenant_id VARCHAR NOT NULL,"
            # ``idea_id`` is a plain indexed column, NOT a FK (BL-030): a FK to the
            # hot, pre-existing ``ideas`` table takes a SHARE ROW EXCLUSIVE lock that
            # HANGS the blue/green deploy behind any live connection on ``ideas``
            # (backend_green never healthy). ``business_requirement_id`` keeps its FK
            # - that table is created just above in this same migration (no lock
            # contention). Integrity for idea_id is enforced tenant-scoped in the
            # service layer.
            "  idea_id VARCHAR NOT NULL,"
            f'  business_requirement_id VARCHAR NOT NULL REFERENCES "{s}".business_requirements(id),'
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_idea_business_requirement UNIQUE (idea_id, business_requirement_id)"
            ")"
        )
    )
    for col in ("tenant_id", "idea_id", "business_requirement_id"):
        bind.execute(
            text(
                f'CREATE INDEX IF NOT EXISTS ix_idea_business_requirements_{col} '
                f'ON "{s}".idea_business_requirements ({col})'
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from modules.ideation.db import IDEATION_SCHEMA as s

    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".idea_business_requirements'))
    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".business_requirements'))
    bind.execute(
        text(f'DROP TABLE IF EXISTS "{s}".ideation_artifact_template_versions')
    )
    bind.execute(text(f'DROP TABLE IF EXISTS "{s}".ideation_artifact_templates'))
