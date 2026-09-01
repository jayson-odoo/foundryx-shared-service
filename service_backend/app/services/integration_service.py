"""Integration service (plan 09 §4, §6) - business rules over the connection
registry: one-per-type (plan 06 D7), credential encryption (write-only),
inline test with status upkeep, Resource-list reads (plan 06 D6).
"""
import csv
import io
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.integrations import all_providers, get_provider
from app.integrations.base import IntegrationProvider, TestResult
from app.models.connection import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_ERROR,
    CONNECTION_STATUS_UNVERIFIED,
    EXEMPT_FROM_ONE_PER_TYPE,
    Connection,
)
from app.repositories.connection_repository import ConnectionRepository
from app.schemas.integration import (
    ConnectionCreateRequest,
    ConnectionOut,
    ConnectionUpdateRequest,
    ProviderOut,
    TestResultOut,
)
from app.schemas.user import FilterGroup
from app.secrets import decrypt_secret, encrypt_secret
from app.services.filter_translator import translate_filter
from app.workflow_engine.entity_events import emit_entity_event

# Whitelisted filterable columns (never arbitrary attributes - the translator
# contract). Wire names are camelCase like every Resource entity.
_CONNECTION_FILTER_COLUMNS = {
    "name": Connection.name,
    "provider": Connection.provider,
    "type": Connection.type,
    "status": Connection.status,
    "lastTestedAt": Connection.last_tested_at,
    "created": Connection.created_at,
}


def _now() -> datetime:
    # House convention since plan sprint-2/05: AWARE UTC everywhere (columns are timestamptz).
    return datetime.now(timezone.utc)


_STALE_CIPHERTEXT_MSG = (
    "Stored credentials can no longer be decrypted (the encryption key changed - "
    "e.g. FERNET_KEY was unset, so a restart rotated the ephemeral key). "
    "Re-enter the credentials and save to fix this connection."
)


def _decrypt_or_none(ciphertext: str) -> Optional[Dict[str, str]]:
    """Decrypt stored credentials; None when the key no longer matches."""
    if not ciphertext:
        return {}
    try:
        return decrypt_secret(ciphertext)
    except InvalidToken:
        return None


def _provider_out(p: IntegrationProvider) -> ProviderOut:
    return ProviderOut(
        provider=p.provider,
        type=p.type,
        title=p.title,
        description=p.description,
        icon=p.icon,
        fields=p.fields(),
        testLabel=p.test_label,
        testTarget=p.test_target,
    )


def _connection_out(c: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        tenantId=c.tenant_id,
        provider=c.provider,
        type=c.type,
        name=c.name,
        config={k: str(v) for k, v in (c.config_json or {}).items()},
        status=c.status,
        isActive=bool(c.is_active),
        lastTestedAt=c.last_tested_at,
        lastError=c.last_error,
        rateLimitPerMinute=c.rate_limit_per_minute,
        createdAt=c.created_at,
        updatedAt=c.updated_at,
    )


class IntegrationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ConnectionRepository(db)

    # ── catalog ──────────────────────────────────────────────────────────
    def providers(self) -> List[ProviderOut]:
        return [_provider_out(p) for p in all_providers()]

    # ── connections (Resource-list contract, plan 06 D6) ─────────────────
    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[ConnectionOut], int]:
        clause = translate_filter(filter_group, _CONNECTION_FILTER_COLUMNS)
        rows, total = self.repo.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=clause,
            providers=self._registered_providers(),
        )
        return [_connection_out(c) for c in rows], total

    @staticmethod
    def _registered_providers() -> List[str]:
        """Provider keys the Integrations surface owns. Infrastructure rows in
        the same ``connections`` table under an unregistered provider (e.g. the
        embed ``omnichannel_shared`` connection) are deliberately excluded - the
        integrations Disconnect action would otherwise destroy them and mint a
        new connection id, invalidating every consumer's embed iframe."""
        return [p.provider for p in all_providers()]

    def get(self, tenant_id: str, connection_id: str) -> ConnectionOut:
        return _connection_out(self._get_or_404(tenant_id, connection_id))

    def get_at(
        self,
        tenant_id: str,
        index: int,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[Optional[ConnectionOut], int]:
        rows, total = self.list(
            tenant_id,
            page=max(index, 0),
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        return (rows[0] if rows else None), total

    def export_csv(
        self,
        tenant_id: str,
        columns: List[str],
        *,
        ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.list(
            tenant_id,
            page=0,
            page_size=100_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        if ids:
            id_set = set(ids)
            rows = [c for c in rows if c.id in id_set]
        titles = {p.provider: p.title for p in all_providers()}
        labels = {
            "name": "Name",
            "provider": "Provider",
            "type": "Type",
            "status": "Status",
            "lastTestedAt": "Last tested",
            "lastError": "Last error",
            "created": "Created",
        }

        def cell(c: ConnectionOut, col: str) -> str:
            if col == "provider":
                return titles.get(c.provider, c.provider)
            value = {
                "name": c.name,
                "type": c.type,
                "status": c.status,
                "lastTestedAt": c.lastTestedAt,
                "lastError": c.lastError,
                "created": c.createdAt,
            }.get(col)
            return "" if value is None else str(value)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([labels.get(c, c) for c in columns])
        for row in rows:
            writer.writerow([cell(row, c) for c in columns])
        return buffer.getvalue()

    def create(self, tenant_id: str, req: ConnectionCreateRequest) -> ConnectionOut:
        provider = get_provider(req.provider)
        if provider is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'Unknown provider "{req.provider}".')
        # ONE connection per TYPE per tenant (plan 06 D7) - resolution must
        # stay deterministic (which bucket does StorageService write to?).
        # Subsumes the old per-provider rule; multiple-per-provider = BL-043.
        # RELAXED for ``payment`` (AC-07-24): a tenant may hold several payment
        # connections (Stripe + Billplz) for per-project resolution; only a
        # SAME-PROVIDER duplicate is rejected (the (tenant, provider) unique).
        # RELAXED for ``llm`` too (Bi-D21 / AC-BI-03b) - agents resolve by
        # connection_id, so Anthropic + OpenAI + Gemini coexist. The exempt set
        # is shared with the DB index so the 409 and the constraint agree.
        # ``erp`` is exempt from the per-PROVIDER rule as well: the
        # ``uq_connection_tenant_provider`` index (app/models/connection.py)
        # carries ``type != 'erp'`` in its predicate because one AutoCount
        # company = one ``autocount``/``sql_database`` connection (sprint-4/13
        # D16/D17, plan 22). Mirror the index exactly - no 409 for erp.
        if provider.type == "erp":
            pass
        elif provider.type in EXEMPT_FROM_ONE_PER_TYPE:
            dup = self.repo.get_by_provider(tenant_id, provider.provider)
            if dup is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f'A {dup.provider} connection ("{dup.name}") already exists '
                    "for this workspace - disconnect it first.",
                )
        else:
            existing = self.repo.get_by_type(tenant_id, provider.type)
            if existing is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f'A {existing.type} connection ("{existing.name}") already exists '
                    "for this workspace - disconnect it first.",
                )
        connection = Connection(
            tenant_id=tenant_id,
            provider=provider.provider,
            type=provider.type,
            name=req.name,
            config_json=dict(req.config),
            credentials_json=encrypt_secret(dict(req.credentials)),
            status=CONNECTION_STATUS_UNVERIFIED,
            rate_limit_per_minute=req.rateLimitPerMinute,
        )
        self.repo.create(connection)
        self.db.flush()
        emit_entity_event(self.db, "connection", "created", connection, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(connection)
        return _connection_out(connection)

    def _guard_not_migrating(self, tenant_id: str, connection_id: str) -> None:
        """A connection tied to a live storage migration (as source A or
        target B) is frozen against edit/delete (sprint-4/10 AC-10-14)."""
        from app.storage_migration.service import StorageMigrationService

        if StorageMigrationService(self.db).is_connection_locked(tenant_id, connection_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This connection is part of a storage migration in progress and "
                "cannot be changed until it finishes.",
            )

    def update(self, tenant_id: str, connection_id: str, req: ConnectionUpdateRequest) -> ConnectionOut:
        connection = self._get_or_404(tenant_id, connection_id)
        self._guard_not_migrating(tenant_id, connection_id)
        changes: dict = {}
        if req.name is not None and connection.name != req.name:
            changes["name"] = {"from": connection.name, "to": req.name}
            connection.name = req.name
        if req.config is not None:
            # MERGE, don't replace - config is a partial PATCH field (its
            # sibling `credentials` merges too); wholesale replace would let a
            # partial body silently wipe omitted keys.
            connection.config_json = {**(connection.config_json or {}), **req.config}
        if req.rateLimitPerMinute is not None:
            connection.rate_limit_per_minute = req.rateLimitPerMinute
        # Write-only secrets: omitted/empty keys keep the stored values.
        if req.credentials:
            # Undecryptable stored blob (key rotated) → start fresh from the
            # incoming values rather than 500ing.
            stored = _decrypt_or_none(connection.credentials_json) or {}
            stored.update({k: v for k, v in req.credentials.items() if v})
            connection.credentials_json = encrypt_secret(stored)
        # Config changes invalidate the last verification.
        connection.status = CONNECTION_STATUS_UNVERIFIED
        connection.last_error = None
        emit_entity_event(self.db, "connection", "updated", connection, tenant_id=tenant_id, changes=changes or None)
        self.db.commit()
        self.db.refresh(connection)
        return _connection_out(connection)

    def set_active(self, tenant_id: str, connection_id: str) -> ConnectionOut:
        """Make a STORAGE connection the tenant's single active write-target
        (sprint-4/12). New uploads land here; resolve-by-type serves it. The
        partial-unique index permits only one active row per (tenant, type), so
        deactivate every other storage row of this tenant FIRST, then activate
        the target - one transaction. Blobs written under a now-retired
        connection keep resolving by key (resolve-by-id ignores is_active)."""
        connection = self._get_or_404(tenant_id, connection_id)
        if connection.type != "storage":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Only a storage connection has an active write-target.",
            )
        self._guard_not_migrating(tenant_id, connection_id)
        if connection.status == CONNECTION_STATUS_ERROR:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Test this connection successfully before making it active.",
            )
        # Two flushes so we never hold two active storage rows at once (the
        # partial-unique index forbids it): deactivate ALL this tenant's storage
        # rows first, flush to zero-active, THEN activate the target.
        rows = (
            self.db.query(Connection)
            .filter(Connection.tenant_id == tenant_id, Connection.type == "storage")
            .all()
        )
        for row in rows:
            row.is_active = False
        self.db.flush()
        connection.is_active = True
        self.db.flush()
        self.db.commit()
        self.db.refresh(connection)
        return _connection_out(connection)

    def delete(self, tenant_id: str, connection_id: str) -> None:
        connection = self._get_or_404(tenant_id, connection_id)
        self._guard_not_migrating(tenant_id, connection_id)
        emit_entity_event(self.db, "connection", "deleted", connection, tenant_id=tenant_id)
        self.repo.delete(connection)
        self.db.commit()

    def test(self, tenant_id: str, connection_id: str, target: Optional[str] = None) -> TestResultOut:
        connection = self._get_or_404(tenant_id, connection_id)
        provider = get_provider(connection.provider)
        if provider is None:  # provider unregistered (module uninstalled)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provider is not available.")
        # A provider may legitimately offer NO test (the meetings notetaker
        # account: verifying it means a real interactive sign-in). Refuse rather
        # than run something weaker and stamp the connection ACTIVE on the
        # strength of it - the row stays UNVERIFIED, which is the truth.
        if not getattr(provider, "test_label", ""):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "This connection has no test.",
            )
        credentials = _decrypt_or_none(connection.credentials_json)
        if credentials is None:
            # Key rotation made the stored secret unreadable - surface a clean,
            # actionable failure instead of a 500.
            result = TestResult(ok=False, message=_STALE_CIPHERTEXT_MSG)
        elif getattr(provider, "test_needs_context", False):
            # A provider whose test has to READ the tenant's own rows opts in
            # with this attribute (meetings' shared-calendar mode probes each
            # opted-in user's calendar). Handing the session over beats making
            # the provider open one of its own, which no test could then steer.
            result = provider.test(
                connection.config_json or {},
                credentials,
                target,
                db=self.db,
                tenant_id=tenant_id,
            )
        else:
            result = provider.test(connection.config_json or {}, credentials, target)
        checked_at = _now()
        connection.status = CONNECTION_STATUS_ACTIVE if result.ok else CONNECTION_STATUS_ERROR
        connection.last_tested_at = checked_at
        connection.last_error = None if result.ok else result.message
        self.db.commit()
        return TestResultOut(ok=result.ok, message=result.message, checkedAt=checked_at)

    def _get_or_404(self, tenant_id: str, connection_id: str) -> Connection:
        connection = self.repo.get(connection_id, tenant_id)
        # Infrastructure rows under an unregistered provider (embed
        # ``omnichannel_shared``) are not part of the Integrations surface - hide
        # them from detail/test/disconnect just as they're hidden from the list.
        if connection is None or get_provider(connection.provider) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found.")
        return connection
