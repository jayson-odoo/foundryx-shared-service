"""Sandboxed Code action (sprint-4/19 S4): ``workflows.code`` permission + grant
sweep, and ``workflow_versions.code_authorized_by``.

A new core permission does NOT reach existing tenants' Admin automatically -
this migration grants it to every non-platform tenant's Admin role (DoD rule).
Custom roles are untouched. Revision id length: 14 chars (<= 32).

Revision ID: code_action_s4
Revises: serialized_run_s4
Create Date: 2026-08-30
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "code_action_s4"
down_revision: Union[str, Sequence[str], None] = "serialized_run_s4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "workflows.code"


def upgrade() -> None:
    op.add_column("workflow_versions", sa.Column("code_authorized_by", sa.String(), nullable=True))

    bind = op.get_bind()
    perm_id = bind.execute(sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": _KEY}).scalar()
    if perm_id is None:
        perm_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO permissions "
                "(id, key, module, resource, resource_label, action, action_label, description) "
                "VALUES (:id, :key, 'core', 'workflows', 'Workflows', 'code', 'Author code', "
                "'Can add and edit / publish / run workflow Code nodes (sandboxed Python)')"
            ),
            {"id": perm_id, "key": _KEY},
        )
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
    perm_id = bind.execute(sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": _KEY}).scalar()
    if perm_id is not None:
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"), {"pid": perm_id})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": perm_id})
    op.drop_column("workflow_versions", "code_authorized_by")
