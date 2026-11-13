"""HTTP request action (plan sprint-4/31 S5, D-A5-12/AC-WFP-61): ``workflows.http``
permission + grant sweep.

A new core permission does NOT reach existing tenants' Admin automatically -
this migration grants it to every non-platform tenant's Admin role, mirroring
`code_action_s4`'s ``workflows.code`` sweep exactly (DoD rule). Custom roles
are untouched. Revision id length: 18 chars (<= 32).

Revision ID: workflows_http_s31
Revises: wf_run_pause_s31
Create Date: 2026-09-07
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "workflows_http_s31"
down_revision: Union[str, Sequence[str], None] = "wf_run_pause_s31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "workflows.http"


def upgrade() -> None:
    bind = op.get_bind()
    perm_id = bind.execute(sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": _KEY}).scalar()
    if perm_id is None:
        perm_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO permissions "
                "(id, key, module, resource, resource_label, action, action_label, description) "
                "VALUES (:id, :key, 'core', 'workflows', 'Workflows', 'http', 'Author HTTP request', "
                "'Can add and edit / publish / run workflow HTTP request nodes')"
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
