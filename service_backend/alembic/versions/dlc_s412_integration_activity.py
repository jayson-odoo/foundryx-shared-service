"""integration_activity table + integration_logs permissions + grant sweep.

sprint-4/12 Slice 1 (Developer Logs / Integration Activity console):
- ``integration_activity`` core ``public`` table (source-tagged generic log) +
  the five ``(tenant_id, …)`` composite indexes (AC-DLC-01).
- The two core permission rows ``integration_logs.read`` / ``.manage``, and a
  grant sweep so EXISTING tenants' Admin roles receive them (a new core
  permission is otherwise only granted at provision/seed — DoD backfill rule,
  AC-DLC-08). ``sweep_tenant_admin_grants`` at bootstrap is belt-and-suspenders.

Deploy via ``bootstrap_db`` (runs ``alembic upgrade``), NOT ``init_db``.

Revision id: ``dlc_s412_integration_activity`` (29 chars ≤ 32).

Revision ID: dlc_s412_integration_activity
Revises: migrate_storage_perm410
Create Date: 2026-07-11
"""
import uuid
from typing import Sequence, Union

import app.models.utc_datetime  # noqa: F401 (registers the UTCDateTime type)
import sqlalchemy as sa
from alembic import op

revision: str = "dlc_s412_integration_activity"
down_revision: Union[str, Sequence[str], None] = "migrate_storage_perm410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMS = [
    (
        "integration_logs.read",
        "integration_logs",
        "Developer Logs",
        "read",
        "View developer logs",
        "Can view the integration activity console "
        "(inbound API / embed / outbound / webhook logs)",
    ),
    (
        "integration_logs.manage",
        "integration_logs",
        "Developer Logs",
        "manage",
        "Manage developer logs",
        "Can configure log retention and manage the integration activity console",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "integration_activity" not in insp.get_table_names():
        op.create_table(
            "integration_activity",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("trace_id", sa.String(), nullable=True, index=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True, index=True),
            sa.Column("api_key_id", sa.String(), nullable=True),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("external_ref", sa.String(), nullable=True),
            sa.Column("request_summary_json", sa.JSON(), nullable=True),
            sa.Column("response_summary_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_integration_activity_tenant_created",
            "integration_activity",
            ["tenant_id", "created_at"],
        )
        op.create_index(
            "ix_integration_activity_tenant_trace",
            "integration_activity",
            ["tenant_id", "trace_id"],
        )
        op.create_index(
            "ix_integration_activity_tenant_source",
            "integration_activity",
            ["tenant_id", "source"],
        )
        op.create_index(
            "ix_integration_activity_tenant_status",
            "integration_activity",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_integration_activity_tenant_extref",
            "integration_activity",
            ["tenant_id", "external_ref"],
        )

    # ── permissions + grant sweep ──
    for key, resource, resource_label, action, action_label, description in _PERMS:
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": key}
        ).scalar()
        if perm_id is None:
            perm_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO permissions "
                    "(id, key, module, resource, resource_label, action, "
                    "action_label, description) VALUES "
                    "(:id, :key, 'core', :resource, :resource_label, :action, "
                    ":action_label, :description)"
                ),
                {
                    "id": perm_id,
                    "key": key,
                    "resource": resource,
                    "resource_label": resource_label,
                    "action": action,
                    "action_label": action_label,
                    "description": description,
                },
            )
        # Grant to every non-platform tenant's Admin role that lacks it.
        # (association tenant_id is derived from the owning role.)
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id, tenant_id) "
                "SELECT r.id, :pid, r.tenant_id "
                "FROM roles r JOIN tenants t ON t.id = r.tenant_id "
                "WHERE r.name = 'Admin' AND t.is_platform = false "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM role_permissions rp "
                "  WHERE rp.role_id = r.id AND rp.permission_id = :pid)"
            ),
            {"pid": perm_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for key, *_ in _PERMS:
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": key}
        ).scalar()
        if perm_id is not None:
            bind.execute(
                sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"),
                {"pid": perm_id},
            )
            bind.execute(
                sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": perm_id}
            )
    op.drop_table("integration_activity")
