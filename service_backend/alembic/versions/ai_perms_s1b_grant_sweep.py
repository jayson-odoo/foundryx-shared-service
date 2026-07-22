"""AI permissions + grant sweep for existing tenants (Phase B-i S1, AC-BI-14)

A new core permission does NOT reach already-provisioned tenants' Admin roles —
the grant is computed at provision/seed time. Without this sweep the AI surfaces
would silently 403 (or simply not render) for every tenant created before this
slice. That is Definition-of-Done #4, and it is the single most repeated gap in
this codebase's history.

Grants `ai_agents.read` / `ai_agents.manage` / `ai_traces.read`. Note the
deliberate SEPARATION of `ai_traces.read` (AC-BI-14): traces hold raw prompts and
completions, so trace access can be granted without granting the ability to
re-key providers or rewrite prompts — and vice versa. Both land on Admin here;
the split matters for every narrower role an operator builds.

LLM *connections* need NO new permission — they ride the existing
`integrations.read` / `integrations.manage`.

Idempotent and order-independent: `PermissionRepository.sync` upserts the
catalog row IN PLACE (matches by key, keeps the id), so ids minted here survive
a later catalog sync and the grants stay valid.

Revision id length: 24 chars (≤ 32).

Revision ID: ai_perms_s1b_grant_sweep
Revises: ai_core_s1b
Create Date: 2026-07-21
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ai_perms_s1b_grant_sweep"
down_revision: Union[str, Sequence[str], None] = "ai_core_s1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (key, resource, resource_label, action, action_label, description)
_PERMISSIONS = [
    (
        "ai_agents.read",
        "ai_agents",
        "AI Agents",
        "read",
        "View AI agents",
        "Can view AI agents and skills",
    ),
    (
        "ai_agents.manage",
        "ai_agents",
        "AI Agents",
        "manage",
        "Manage AI agents",
        "Can create / edit AI agents and skill prompts",
    ),
    (
        "ai_traces.read",
        "ai_traces",
        "AI Traces",
        "read",
        "View AI traces",
        "Can view AI run traces including raw prompts and completions",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    for key, resource, resource_label, action, action_label, description in _PERMISSIONS:
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :k"), {"k": key}
        ).scalar()
        if perm_id is None:
            perm_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO permissions "
                    "(id, key, module, resource, resource_label, action, action_label, description) "
                    "VALUES (:id, :key, 'core', :resource, :resource_label, :action, "
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
        # `tenant_id` on the association is derived from the OWNING ROLE
        # (BL-015) — never a static default.
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
    for key, *_ in _PERMISSIONS:
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
