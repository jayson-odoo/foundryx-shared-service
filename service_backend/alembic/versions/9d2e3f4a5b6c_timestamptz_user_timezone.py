"""Datetime hygiene (plan sprint-2/05, BL-012): every core DateTime column →
timestamptz, + users.timezone preference.

Existing values are naive UTC BY CONVENTION — `USING <col> AT TIME ZONE 'UTC'`
pins that interpretation explicitly (an implicit cast would read them in the
SESSION timezone and silently shift every historical timestamp).

Omnichannel tables were created `timezone=True` from day one (create_all) —
nothing to do there.

Revision ID: 9d2e3f4a5b6c
Revises: 8c1d2e3f4a5b
Create Date: 2026-06-06 22:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9d2e3f4a5b6c"
down_revision: Union[str, None] = "8c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every naive-UTC core column (from Base.metadata at plan time).
TZ_COLUMNS: dict[str, list[str]] = {
    "auth_throttle": ["window_start", "locked_until", "created_at"],
    "email_outbox": ["next_attempt_at", "created_at", "sent_at"],
    "modules": ["created_at", "updated_at"],
    "notification_specs": ["created_at", "updated_at"],
    "permissions": ["created_at"],
    "statuses": ["created_at", "updated_at"],
    "status_transitions": ["created_at", "updated_at"],
    "tenants": ["created_at", "updated_at"],
    "connections": ["last_tested_at", "created_at", "updated_at"],
    "roles": ["created_at", "updated_at"],
    "tenant_branding": ["created_at", "updated_at"],
    "tenant_modules": ["installed_at", "updated_at"],
    "users": ["created_at", "updated_at", "last_sign_in_at", "email_verified_at"],
    "email_change_requests": ["expires_at", "completed_at", "created_at"],
    "impersonation_sessions": ["started_at", "ended_at"],
    "invite_tokens": ["expires_at", "used_at", "created_at"],
    "user_roles": ["assigned_at"],
    "user_view_preferences": ["created_at", "updated_at"],
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        for table, columns in TZ_COLUMNS.items():
            for column in columns:
                op.alter_column(
                    table,
                    column,
                    type_=sa.DateTime(timezone=True),
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )
    # SQLite (tests/dev fallback) stores datetimes as text — no type change.

    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "timezone")
    if _is_postgres():
        for table, columns in TZ_COLUMNS.items():
            for column in columns:
                op.alter_column(
                    table,
                    column,
                    type_=sa.DateTime(timezone=False),
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )
