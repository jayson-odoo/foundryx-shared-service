"""Company service — registering an AutoCount company database and seeding its
per-entity config + mapping rows.

**A company is DISCOVERED, never typed** (AC-13-01/D16). The operator supplies a
connection; we sign in and read ``DatabaseName``/``CompanyName`` back. The
vendor API has no company parameter at all — the server resolves it from the
``AppId`` header — so asking an operator to name the company would be asking for
a value that is silently overridden. Worse, it would let two connections claim
the same company under different labels.

Company identity is therefore ``database_name``, enforced UNIQUE per tenant by
``ac_company``. Core's ``uq_connection_tenant_provider`` was carved out for
``erp`` precisely so this owns it — core keeps zero AutoCount knowledge.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, record_activity
from ..client import AutoCountClient, AutoCountError
from ..mapping import DEFAULT_MAPPINGS, MappingRow
from ..models import (
    SYNC_MODE_SCHEDULED_REVIEW,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from ..provider import PROVIDER_KEY, client_from_connection
from ..repositories import (
    CompanyRepository,
    ConnectionRepository,
    EntityConfigRepository,
    FieldMappingRepository,
)

logger = logging.getLogger("foundryx.autocount")

# Entities a new company is configured for. GRN only in slice 1 — a config row
# for an entity with no pipeline behind it would offer an operator a sync that
# silently does nothing.
from ..canonical.grn import ENTITY_GOODS_RECEIVED_NOTE  # noqa: E402

SEEDED_ENTITIES = (ENTITY_GOODS_RECEIVED_NOTE,)


class AutocountServiceError(Exception):
    """Base — carries an operator-safe message (never a stack trace, never a
    credential)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConnectionNotFound(AutocountServiceError):
    pass


class CompanyNotFound(AutocountServiceError):
    pass


class CompanyAlreadyExists(AutocountServiceError):
    pass


class CompanyService:
    def __init__(self, db: Session):
        self.db = db
        self.companies = CompanyRepository(db)
        self.configs = EntityConfigRepository(db)
        self.mappings = FieldMappingRepository(db)
        self.connections = ConnectionRepository(db)

    # ── reads ────────────────────────────────────────────────────────────────

    def list(
        self, tenant_id: str, *, page: int = 0, page_size: int = 25
    ) -> Tuple[List[AcCompany], int]:
        return self.companies.list(tenant_id, page=page, page_size=page_size)

    def get(self, tenant_id: str, company_id: str) -> AcCompany:
        company = self.companies.get(tenant_id, company_id)
        if company is None:
            raise CompanyNotFound("That AutoCount company was not found.")
        return company

    def entity_configs(self, tenant_id: str, company_id: str) -> List[AcEntityConfig]:
        self.get(tenant_id, company_id)  # tenant-scope guard before any read
        return self.configs.list_for_company(tenant_id, company_id)

    # ── connection resolution ────────────────────────────────────────────────

    def _connection(self, tenant_id: str, connection_id: str) -> Connection:
        """Tenant-scoped connection lookup. NEVER a bare ``get(id)`` — a stored
        id resolved unscoped is the polymorphic-target_id leak class. The query
        itself lives in the repository layer (Router → Service → Repository)."""
        conn = self.connections.get_for_provider(
            tenant_id, connection_id, PROVIDER_KEY
        )
        if conn is None:
            raise ConnectionNotFound("That AutoCount connection was not found.")
        return conn

    def credentials(self, connection: Connection) -> Dict[str, Any]:
        """Decrypt a connection's credentials. A wrong/rotated ``FERNET_KEY``
        yields a CLEAN rejection, never a 500 — and the message never echoes any
        ciphertext."""
        if not connection.credentials_json:
            return {}
        try:
            return decrypt_secret(connection.credentials_json)
        except InvalidToken as exc:
            raise AutocountServiceError(
                "This connection's stored credentials can no longer be decrypted. "
                "Re-enter the AppId and password."
            ) from exc

    def client_for(
        self, tenant_id: str, company: AcCompany, *, transport: Any = None
    ) -> AutoCountClient:
        conn = self._connection(tenant_id, company.connection_id)
        return client_from_connection(
            conn.config_json or {}, self.credentials(conn), transport=transport
        )

    # ── create (discovery) ───────────────────────────────────────────────────

    def create_from_connection(
        self,
        tenant_id: str,
        connection_id: str,
        *,
        name: str = "",
        transport: Any = None,
    ) -> AcCompany:
        """Sign in, DISCOVER the company, and register it.

        The sign-in is not ceremony: it is the only way to learn which company
        an ``AppId`` selects. Registering without it would let an operator
        create two rows for one company, each with its own watermark — which
        would double-deliver every document.
        """
        conn = self._connection(tenant_id, connection_id)

        existing_for_conn = self.companies.get_by_connection(tenant_id, connection_id)
        if existing_for_conn is not None:
            raise CompanyAlreadyExists(
                f"That connection is already registered as company "
                f"'{existing_for_conn.database_name}'."
            )

        client = client_from_connection(
            conn.config_json or {}, self.credentials(conn), transport=transport
        )
        try:
            session = client.login()
        except AutoCountError as exc:
            record_activity(
                self.db,
                tenant_id=tenant_id,
                operation="POST /api/Server/Login",
                status=ACTIVITY_ERROR,
                error_message=exc.message,
                external_ref=connection_id,
            )
            raise AutocountServiceError(exc.message) from exc
        finally:
            client.close()

        database_name = (session.database_name or "").strip()
        if not database_name:
            raise AutocountServiceError(
                "AutoCount signed in but did not report a company database name, so "
                "the company cannot be identified. Check the AppId."
            )

        record_activity(
            self.db,
            tenant_id=tenant_id,
            operation="POST /api/Server/Login",
            status=ACTIVITY_SUCCESS,
            external_ref=database_name,
            response={"databaseName": database_name, "companyName": session.company_name},
        )

        if self.companies.get_by_database_name(tenant_id, database_name) is not None:
            raise CompanyAlreadyExists(
                f"Company '{database_name}' is already connected. Each AutoCount "
                f"company may be connected once."
            )

        company = self.companies.add(
            AcCompany(
                tenant_id=tenant_id,
                connection_id=connection_id,
                database_name=database_name,
                company_name=session.company_name or "",
                name=(name or session.company_name or database_name).strip(),
                is_active=True,
            )
        )
        self.seed_company_defaults(tenant_id, company.id)
        self.db.commit()
        return company

    # ── seeding ──────────────────────────────────────────────────────────────

    def seed_company_defaults(self, tenant_id: str, company_id: str) -> None:
        """Seed per-entity config + the DEFAULT mapping rows.

        Seed-if-absent is correct HERE (a brand-new company has nothing to
        preserve) and only here. After this moment the DATABASE is the source of
        truth for mapping: the defaults are never re-applied, so an operator's
        edits are never silently reverted by a deploy.
        """
        for entity_type in SEEDED_ENTITIES:
            if self.configs.get(tenant_id, company_id, entity_type) is None:
                self.configs.add(
                    AcEntityConfig(
                        tenant_id=tenant_id,
                        company_id=company_id,
                        entity_type=entity_type,
                        # GRN starts gated: a human sees the first batches before
                        # anything reaches a consumer (plan §9).
                        sync_mode=SYNC_MODE_SCHEDULED_REVIEW,
                        source_impl="autocount_read",
                    )
                )
            if self.mappings.count(tenant_id, company_id, entity_type) == 0:
                self._seed_mapping_rows(tenant_id, company_id, entity_type)
        self.db.flush()

    def _seed_mapping_rows(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> None:
        rows: Tuple[MappingRow, ...] = DEFAULT_MAPPINGS.get(entity_type, ())
        for order, row in enumerate(rows):
            self.mappings.add(
                AcFieldMapping(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    scope=row.scope,
                    source_path=row.source_path,
                    canonical_field=row.canonical_field,
                    transform=row.transform,
                    is_required=row.is_required,
                    is_enabled=row.is_enabled,
                    sort_order=order,
                )
            )

    def mapping_rows(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> List[MappingRow]:
        """DB rows → engine rows. The DB is the source of truth (D5) — there is
        deliberately NO fallback to ``DEFAULT_MAPPINGS`` here: a company whose
        rows were all deleted must map nothing and say so, not quietly resume
        the built-in behaviour an operator thought they had removed."""
        return [
            MappingRow(
                source_path=row.source_path,
                canonical_field=row.canonical_field,
                transform=row.transform,
                scope=row.scope,
                is_required=row.is_required,
                is_enabled=row.is_enabled,
            )
            for row in self.mappings.list(tenant_id, company_id, entity_type)
        ]
