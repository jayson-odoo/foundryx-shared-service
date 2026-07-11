"""integrations.migrate_storage permission + grant sweep (sprint-4/10 Slice 2)

A new core permission does NOT reach existing tenants' Admin automatically (the
grant is computed at provision/seed). This migration ships the grant sweep for
already-provisioned tenants (DoD backfill rule): it ensures the
``integrations.migrate_storage`` permission row exists, then grants it to every
non-platform tenant's Admin role that lacks it.

Idempotent, order-independent: ``PermissionRepository.sync`` upserts the catalog
row IN PLACE (matches by key, keeps the id), so the id this migration mints
survives a later catalog sync and the grants stay valid. The seed path's
``sweep_tenant_admin_grants`` is the belt-and-suspenders that also covers it.

Revision id length: 23 chars (≤ 32).

Revision ID: migrate_storage_perm410
Revises: conn_is_active_s410
Create Date: 2026-07-11
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "migrate_storage_perm410"
down_revision: Union[str, Sequence[str], None] = "conn_is_active_s410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "integrations.migrate_storage"


def upgrade() -> None:
    bind = op.get_bind()

    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": _KEY}
    ).scalar()
    if perm_id is None:
        perm_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO permissions "
                "(id, key, module, resource, resource_label, action, action_label, description) "
                "VALUES (:id, :key, 'core', 'integrations', 'Integrations', "
                "'migrate_storage', 'Migrate storage', "
                "'Migrate assets to a new storage bucket')"
            ),
            {"id": perm_id, "key": _KEY},
        )

    # Grant to every non-platform tenant's Admin role that doesn't already hold
    # it. tenant_id on the association is derived from the owning role.
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
    perm_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": _KEY}
    ).scalar()
    if perm_id is not None:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :pid"),
            {"pid": perm_id},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :pid"), {"pid": perm_id}
        )
