"""connections: restore the 'erp' carve-out on uq_connection_tenant_type (sprint-5/01)

``ac_erp_multi_s413`` widened the one-active-per-type predicate to
``type NOT IN ('payment','erp')`` so a tenant can hold several active ERP
connections (one AutoCount company per connection). ``ai_core_s1b_ai_subsystem``
later rebuilt the same index to add ``llm`` - but copied the ORIGINAL predicate
and so silently DROPPED ``erp``:

    intended (model, EXEMPT_FROM_ONE_PER_TYPE): type NOT IN ('payment','erp','llm') AND is_active
    live after ai_core_s1b:                     type NOT IN ('payment','llm')       AND is_active

Invisible to the create_all pytest suite (which builds the index from the
model), visible on every real deploy: an API-backed AutoCount company plus a
``sql_database`` connection (both ``type='erp'``) raises UniqueViolation at
connection create. Surfaced by the sprint-5/01 DB-only company live-verify.

No data change - the predicate only widens, every existing row stays valid.
Revision id length 16 (<= 32, ``alembic_version.version_num`` VARCHAR(32)).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "conn_erp_llm_s501"
down_revision: Union[str, Sequence[str], None] = "run_heartbeat_s4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type NOT IN ('payment', 'erp', 'llm') AND is_active"),
        sqlite_where=sa.text("type NOT IN ('payment', 'erp', 'llm') AND is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type NOT IN ('payment', 'llm') AND is_active"),
        sqlite_where=sa.text("type NOT IN ('payment', 'llm') AND is_active"),
    )
