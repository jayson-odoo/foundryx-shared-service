"""connections: carve 'erp' out of uq_connection_tenant_type (sprint-4/13 D17)

AutoCount is multi-company (D16) and the vendor API resolves the company
server-side from the ``AppId`` request header — there is no company parameter
anywhere. So **AppId IS the company selector** and multi-company means ONE
CONNECTION PER COMPANY, all of ``type='erp'``, all active at once (AC-13-02).

The one-active-per-type partial-unique index therefore gains ``erp`` alongside
the pre-existing ``payment`` carve-out:

    before: type != 'payment'              AND is_active
    after:  type NOT IN ('payment','erp')  AND is_active

Storage and email keep the one-active-per-type invariant EXACTLY as before —
``resolve_for_type`` still resolves a single deterministic write-target for
those. No data change: this only widens a uniqueness predicate, so every
existing row remains valid and no backfill is required.

Revision id length: 17 chars (<= 32 — ``alembic_version.version_num`` is
VARCHAR(32); a longer id passes create_all-based pytest but breaks real deploy).

Revision ID: ac_erp_multi_s413
Revises: dlc_s412b_log_settings
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ac_erp_multi_s413"
down_revision: Union[str, Sequence[str], None] = "dlc_s412b_log_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type NOT IN ('payment', 'erp') AND is_active"),
        sqlite_where=sa.text("type NOT IN ('payment', 'erp') AND is_active"),
    )
    # The TYPE carve-out alone is NOT sufficient: every AutoCount company is
    # provider='autocount', so a tenant's second company is the SAME provider
    # again and the sibling index would reject it. (Payment never hit this —
    # Stripe + Billplz are different providers.) Company-identity uniqueness
    # moves to the module's own ac_company (tenant_id, database_name).
    op.drop_index("uq_connection_tenant_provider", table_name="connections")
    op.create_index(
        "uq_connection_tenant_provider",
        "connections",
        ["tenant_id", "provider"],
        unique=True,
        postgresql_where=sa.text("type != 'erp' AND is_active"),
        sqlite_where=sa.text("type != 'erp' AND is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_connection_tenant_provider", table_name="connections")
    op.create_index(
        "uq_connection_tenant_provider",
        "connections",
        ["tenant_id", "provider"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active"),
    )
    # Reverting is only safe while no tenant holds two active 'erp' rows; a
    # tenant that has onboarded a second AutoCount company must retire one
    # first (the index creation below will fail loudly otherwise — deliberate,
    # silently dropping a company's connection would be far worse).
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type != 'payment' AND is_active"),
        sqlite_where=sa.text("type != 'payment' AND is_active"),
    )
