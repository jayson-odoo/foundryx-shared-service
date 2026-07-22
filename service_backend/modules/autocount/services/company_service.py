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
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    record_activity,
    record_client_calls,
)
from ..client import AutoCountClient, AutoCountError
from ..mapping import DEFAULT_MAPPINGS, SCOPE_HEADER, TRANSFORMS, MappingRow
from ..mapping_catalog import (
    SorentoFieldDef,
    accepted_fields,
    accepted_field_names,
    ac_source_fields,
    required_field_names,
    sorento_field_for,
)
from ..models import (
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
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
    WatermarkRepository,
)
from ..sinks import EntitySink, UnknownSinkImpl, sink_for
from ..sinks_sorento import sorento_sink_from_connection
from ..sorento_provider import SORENTO_PROVIDER_KEY

logger = logging.getLogger("foundryx.autocount")

# Entities a new company is configured for.
#
#     !!  ONLY ENTITIES WITH A CONFIRMED, OBSERVED VENDOR PAYLOAD (AC-14-01).  !!
#
# A config row for an entity with no working vendor route offers an operator a
# sync that silently does nothing. Probed live 2026-07-21: ``Stock``,
# ``StockItem``, ``Item``, ``UOM``, ``StockGroup``, ``StockCategory``,
# ``StockLocation`` and ``StockUOM`` all return HTTP 500 with an EMPTY
# ``Message`` — distinct from the wrong-credential signature ("Stream was not
# readable."), and consistent with the route being absent from this wrapper
# build. They are therefore ABSENT here, not present-and-disabled.
#
# This is a STANDING guard, not a one-off: an entity is added only after its real
# payload has been captured, never designed from inference.
from ..canonical.grn import ENTITY_GOODS_RECEIVED_NOTE  # noqa: E402
from ..canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER  # noqa: E402
from ..envelopes import ENVELOPE_ROW_ARRAY, ENVELOPE_STATUS_DICT  # noqa: E402
from ..sources import INITIAL_LOAD_FULL, INITIAL_LOAD_WINDOWED  # noqa: E402

SEEDED_ENTITIES = (ENTITY_GOODS_RECEIVED_NOTE, ENTITY_SUPPLIER, ENTITY_CUSTOMER)


@dataclass(frozen=True)
class EntityDefaults:
    """The per-entity seed. Grouped so the three settings that MUST agree
    (envelope, initial-load policy and the cap that policy implies) are chosen
    together rather than defaulted independently."""

    envelope: str
    initial_load: str
    record_cap: int


# A master's first read is UNBOUNDED (AC-14-25), so its cap must cover the whole
# standing set rather than a day's changes. 5000 is a deliberate over-provision:
# hitting the cap fails the run loudly (AC-13-46) rather than truncating, so the
# cost of being too low is a blocked sync and the cost of being too high is one
# larger response.
#
#     !!  UNVERIFIED AGAINST A LARGE DATASET.  !!
# The live demo holds 106 Creditors and 172 Debtors, so nothing here has been
# exercised anywhere near 5000. Whether the wrapper honours a RecordCount that
# large is untested.
MASTER_RECORD_CAP = 5000

ENTITY_DEFAULTS: Dict[str, EntityDefaults] = {
    ENTITY_GOODS_RECEIVED_NOTE: EntityDefaults(
        envelope=ENVELOPE_STATUS_DICT,
        initial_load=INITIAL_LOAD_WINDOWED,
        record_cap=200,
    ),
    ENTITY_SUPPLIER: EntityDefaults(
        envelope=ENVELOPE_ROW_ARRAY,
        initial_load=INITIAL_LOAD_FULL,
        record_cap=MASTER_RECORD_CAP,
    ),
    ENTITY_CUSTOMER: EntityDefaults(
        envelope=ENVELOPE_ROW_ARRAY,
        initial_load=INITIAL_LOAD_FULL,
        record_cap=MASTER_RECORD_CAP,
    ),
}


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


class EntityConfigNotFound(AutocountServiceError):
    pass


# The first sync of a brand-new company reaches back exactly this far
# (``AcEntityConfig.initial_lookback_days``, default 30). Anything older is
# INVISIBLE until the supervised full initial load lands (D20, slice 3) — which
# is precisely why the value has to be shown to an operator and be adjustable,
# rather than sitting silently in a column nobody can see.
MIN_LOOKBACK_DAYS = 1
MAX_LOOKBACK_DAYS = 3650


@dataclass
class EntityState:
    """One configured entity PLUS its live delta state.

    Flat and snake_cased on purpose: ``EntityConfigItem.model_validate`` maps it
    straight through ``from_attributes``, so no hand-written wire mapping can
    drift from the schema.

    The watermark half is what makes a zero-record sync explicable. Without
    ``last_success_at``/``watermark_at`` on the surface, "0 records" is
    indistinguishable from "broken", and ``consecutive_failures``/``last_error``
    were already being recorded and shown to nobody.
    """

    id: str
    entity_type: str
    sync_mode: str
    source_impl: str
    envelope: str
    initial_load: str
    record_cap: int
    initial_lookback_days: int
    enabled: bool
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    watermark_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None


@dataclass(frozen=True)
class MappingWriteRow:
    """One row of a mapping-editor save (plan 15 §2, AC-15-41).

    ``sorento_field`` is the Sorento-facing target the operator picked; the
    service maps it back to the stored ``canonical_field`` (they are equal for
    master sink fields). Only these three are operator-authored — ``scope`` and
    the required/enabled flags are derived server-side so the editor cannot
    invent them.
    """

    source_path: str
    transform: str
    sorento_field: str


@dataclass
class MappingRowView:
    """One projected mapping row (AC-15-40). ``sorento_field`` is ``None`` when
    the stored ``canonical_field`` is not delivered to Sorento (identity /
    watermark provenance like ``last_modified``, or an ``extras`` key) — shown as
    non-delivered rather than hidden.

    Flat + snake_cased so ``MappingRowOut.model_validate`` maps it straight
    through ``from_attributes``."""

    source_path: str
    transform: str
    sorento_field: Optional[str]
    canonical_field: str
    scope: str
    is_required: bool
    is_enabled: bool


@dataclass
class MappingView:
    """The mapping-editor payload: the current rows + the two catalogs the
    editor's pickers need (AC-15-40..43)."""

    entity_type: str
    rows: List[MappingRowView]
    sorento_fields: List[SorentoFieldDef]
    ac_fields: List[str]


class CompanyService:
    def __init__(self, db: Session):
        self.db = db
        self.companies = CompanyRepository(db)
        self.configs = EntityConfigRepository(db)
        self.mappings = FieldMappingRepository(db)
        self.connections = ConnectionRepository(db)
        self.watermarks = WatermarkRepository(db)

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

    def entity_states(self, tenant_id: str, company_id: str) -> List[EntityState]:
        """Configured entities joined with their watermarks — TWO queries total,
        never one per entity (the catalogue is heading for nine-plus rows).

        A missing watermark row is normal: it means this entity has never been
        synced, and the surface must show that as "never", not as an error.
        """
        self.get(tenant_id, company_id)  # tenant-scope guard before any read
        marks = {
            row.entity_type: row
            for row in self.watermarks.list_for_company(tenant_id, company_id)
        }
        states: List[EntityState] = []
        for config in self.configs.list_for_company(tenant_id, company_id):
            mark = marks.get(config.entity_type)
            states.append(
                EntityState(
                    id=config.id,
                    entity_type=config.entity_type,
                    sync_mode=config.sync_mode,
                    source_impl=config.source_impl,
                    envelope=config.envelope,
                    initial_load=config.initial_load,
                    record_cap=config.record_cap,
                    initial_lookback_days=config.initial_lookback_days,
                    enabled=config.enabled,
                    last_success_at=mark.last_success_at if mark else None,
                    last_attempt_at=mark.last_attempt_at if mark else None,
                    watermark_at=mark.last_modified_at if mark else None,
                    consecutive_failures=(mark.consecutive_failures or 0) if mark else 0,
                    last_error=mark.last_error if mark else None,
                )
            )
        return states

    # ── entity config edits ──────────────────────────────────────────────────

    def update_entity_config(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        initial_lookback_days: Optional[int] = None,
    ) -> EntityState:
        """Adjust one entity's sync configuration.

        Only ``initial_lookback_days`` is writable today, and only because the
        default of 30 days silently hides a customer's whole back-catalogue on a
        newly connected company. Changing it does NOT re-fetch anything: it only
        governs the window used when no watermark exists yet, which is why the
        surface must say so rather than implying a backfill. The supervised full
        initial load is D20 / slice 3.
        """
        self.get(tenant_id, company_id)  # tenant-scope guard before any write
        config = self.configs.get(tenant_id, company_id, entity_type)
        if config is None:
            raise EntityConfigNotFound(
                f"'{entity_type}' is not configured for sync on this company."
            )
        if initial_lookback_days is not None:
            if not (MIN_LOOKBACK_DAYS <= initial_lookback_days <= MAX_LOOKBACK_DAYS):
                raise AutocountServiceError(
                    f"The initial lookback must be between {MIN_LOOKBACK_DAYS} and "
                    f"{MAX_LOOKBACK_DAYS} days."
                )
            config.initial_lookback_days = initial_lookback_days
        self.db.commit()

        return self._entity_state(tenant_id, company_id, entity_type)

    def refetch_entity(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> EntityState:
        """Re-open the first-run window: RESET the entity's watermark so the next
        sync fetches from scratch again (a full/windowed initial load rather than
        a delta from the last high-water mark).

        This is the explicit, deliberate act behind the "Re-fetch history" action
        (AC-15-30): once an entity has synced, its first-run window is spent and
        the lookback box is inert — the ONLY way to widen history again is to drop
        the watermark. Distinct from ``update_entity_config`` precisely so a
        window edit never silently re-fetches and a re-fetch is never mistaken for
        a config tweak.
        """
        self.get(tenant_id, company_id)  # tenant-scope guard before any write
        config = self.configs.get(tenant_id, company_id, entity_type)
        if config is None:
            raise EntityConfigNotFound(
                f"'{entity_type}' is not configured for sync on this company."
            )
        mark = self.watermarks.get(tenant_id, company_id, entity_type)
        if mark is not None:
            # Clear the delta position and the failure bookkeeping — the next run
            # starts clean. cursor_json (a mid-window resume point) goes too.
            mark.last_modified_at = None
            mark.last_success_at = None
            mark.cursor_json = None
            mark.consecutive_failures = 0
            mark.last_error = None
        self.db.commit()
        return self._entity_state(tenant_id, company_id, entity_type)

    def _entity_state(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> EntityState:
        for state in self.entity_states(tenant_id, company_id):
            if state.entity_type == entity_type:
                return state
        raise EntityConfigNotFound(
            f"'{entity_type}' is not configured for sync on this company."
        )

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

    def _consumer_connection(self, tenant_id: str, connection_id: str) -> Connection:
        """Tenant- AND provider-scoped lookup of the outbound Sorento connection.

        Mirrors ``_connection`` exactly (never a bare ``get(id)`` — a stored
        connection id resolved unscoped is the polymorphic-target_id leak class),
        but pins ``provider='sorento'`` so a company can never be pointed at
        another provider's connection by id."""
        conn = self.connections.get_for_provider(
            tenant_id, connection_id, SORENTO_PROVIDER_KEY
        )
        if conn is None:
            raise ConnectionNotFound("That Sorento connection was not found.")
        return conn

    def sink_for_company(
        self, tenant_id: str, company: AcCompany, entity_type: str
    ) -> EntitySink:
        """Resolve the consumer sink a company delivers to, per entity.

        ``'logging'`` keeps the slice-1 no-op (a legitimate configured default,
        NOT a mock). ``'sorento'`` resolves the company's ``consumer`` connection,
        decrypts its ``apiKey`` (a wrong/rotated ``FERNET_KEY`` yields a CLEAN
        rejection via ``credentials``, never a 500) and builds a per-entity
        ``SorentoSink``. An unknown ``sink_impl`` is a LOUD error — a silent
        fallback to the logging sink would stop delivering to a real consumer
        without anyone noticing.
        """
        impl = company.sink_impl or SINK_IMPL_LOGGING
        if impl == SINK_IMPL_LOGGING:
            # Via the registry (not ``LoggingSink()`` directly) so the sink is
            # swappable the same way the Sorento sink is chosen — one seam.
            return sink_for(SINK_IMPL_LOGGING)
        if impl == SINK_IMPL_SORENTO:
            if not company.sink_connection_id:
                raise AutocountServiceError(
                    "This company is set to push to Sorento but has no Sorento "
                    "connection configured. Choose a target connection first."
                )
            conn = self._consumer_connection(tenant_id, company.sink_connection_id)
            return sorento_sink_from_connection(
                conn.config_json or {},
                self.credentials(conn),  # clean InvalidToken reject, never 500
                entity_type=entity_type,
            )
        raise UnknownSinkImpl(
            f"Company '{company.database_name}' is configured with an unknown "
            f"push sink '{impl}'."
        )

    def set_sink_target(
        self,
        tenant_id: str,
        company_id: str,
        *,
        sink_impl: str,
        sink_connection_id: Optional[str] = None,
    ) -> AcCompany:
        """Point a company at a push target (plan 14 hop 2 — the operator wiring).

        Validates the impl against the known set and, for ``'sorento'``, that the
        connection exists and is genuinely a Sorento ``consumer`` connection for
        THIS tenant (tenant- and provider-scoped, never a bare id). Switching to
        ``'logging'`` clears any stale connection id so a later switch back can't
        resurrect a wrong target.
        """
        company = self.get(tenant_id, company_id)  # tenant-scope guard
        if sink_impl == SINK_IMPL_LOGGING:
            company.sink_impl = SINK_IMPL_LOGGING
            company.sink_connection_id = None
        elif sink_impl == SINK_IMPL_SORENTO:
            if not sink_connection_id:
                raise AutocountServiceError(
                    "Choose a Sorento connection to push to."
                )
            # Proves the connection exists AND is a Sorento consumer for this
            # tenant — 404 otherwise, never a silently-stored dangling id.
            self._consumer_connection(tenant_id, sink_connection_id)
            company.sink_impl = SINK_IMPL_SORENTO
            company.sink_connection_id = sink_connection_id
        else:
            raise AutocountServiceError(
                f"Unknown push target '{sink_impl}'. Choose 'logging' or 'sorento'."
            )
        self.db.commit()
        self.db.refresh(company)
        return company

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
        # ONE trace for the discovery interaction — the HTTP leg and the
        # domain-level outcome below share it.
        trace_id = f"acdiscover-{uuid.uuid4()}"
        try:
            session = client.login()
        except AutoCountError as exc:
            # The real (masked) request/response of the failed login — the leg
            # that previously logged nothing but a message.
            record_client_calls(
                self.db,
                client,
                tenant_id=tenant_id,
                trace_id=trace_id,
                external_ref=connection_id,
            )
            record_activity(
                self.db,
                tenant_id=tenant_id,
                operation="discover company",
                status=ACTIVITY_ERROR,
                trace_id=trace_id,
                error_message=exc.message,
                external_ref=connection_id,
            )
            raise AutocountServiceError(exc.message) from exc
        finally:
            client.close()

        record_client_calls(
            self.db,
            client,
            tenant_id=tenant_id,
            trace_id=trace_id,
            external_ref=connection_id,
        )

        database_name = (session.database_name or "").strip()
        if not database_name:
            raise AutocountServiceError(
                "AutoCount signed in but did not report a company database name, so "
                "the company cannot be identified. Check the AppId."
            )

        record_activity(
            self.db,
            tenant_id=tenant_id,
            operation="discover company",
            status=ACTIVITY_SUCCESS,
            trace_id=trace_id,
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
            defaults = ENTITY_DEFAULTS[entity_type]
            if self.configs.get(tenant_id, company_id, entity_type) is None:
                self.configs.add(
                    AcEntityConfig(
                        tenant_id=tenant_id,
                        company_id=company_id,
                        entity_type=entity_type,
                        # Every entity starts gated: a human sees the first
                        # batches before anything reaches a consumer (plan §9).
                        # Masters especially — they OVERWRITE live data.
                        sync_mode=SYNC_MODE_SCHEDULED_REVIEW,
                        source_impl="autocount_read",
                        envelope=defaults.envelope,
                        initial_load=defaults.initial_load,
                        record_cap=defaults.record_cap,
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

    # ── mapping editor: read + write (plan 15 §2, AC-15-40..43) ───────────────

    def _require_entity(self, tenant_id: str, company_id: str, entity_type: str):
        """Tenant-scope the company, then confirm the entity is one this company
        is configured for — a 404 otherwise, never a mapping surface for an
        entity that does not exist here."""
        self.get(tenant_id, company_id)  # tenant-scope guard (CompanyNotFound)
        config = self.configs.get(tenant_id, company_id, entity_type)
        if config is None:
            raise EntityConfigNotFound(
                f"'{entity_type}' is not configured for sync on this company."
            )
        return config

    def _mapping_view(self, tenant_id: str, company_id: str, entity_type: str) -> MappingView:
        rows = [
            MappingRowView(
                source_path=row.source_path,
                transform=row.transform,
                sorento_field=sorento_field_for(entity_type, row.canonical_field),
                canonical_field=row.canonical_field,
                scope=row.scope,
                is_required=row.is_required,
                is_enabled=row.is_enabled,
            )
            for row in self.mappings.list(tenant_id, company_id, entity_type)
        ]
        return MappingView(
            entity_type=entity_type,
            rows=rows,
            sorento_fields=list(accepted_fields(entity_type)),
            ac_fields=list(ac_source_fields(entity_type)),
        )

    def mapping_view(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> MappingView:
        """The current mapping rows projected AutoCount→Sorento, plus the source
        and target catalogs the editor's pickers need (AC-15-40)."""
        self._require_entity(tenant_id, company_id, entity_type)
        return self._mapping_view(tenant_id, company_id, entity_type)

    def replace_mapping(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        rows: List[MappingWriteRow],
    ) -> MappingView:
        """Replace the DELIVERABLE mapping rows for one (company, entity) in ONE
        transaction (AC-15-41).

        Foolproof guard (AC-15-42/43), enforced server-side — never advisory:
          * every ``sorento_field`` must be in the accepted set (else 422 naming
            the field) — a target Sorento would reject (``extra="forbid"``) can
            never be stored;
          * each accepted field maps once (no duplicate target);
          * ``source_path`` is non-blank; ``transform`` is a known transform.

        Only rows whose canonical field is in the accepted set are replaced —
        provenance/watermark rows (``last_modified``) are PRESERVED, so a re-map
        can never silently break delta sync. This persists to ``ac_field_mapping``
        and is seed-if-absent-safe: ``seed_company_defaults`` only seeds when the
        entity has ZERO rows, so a later ``update_tenant`` never reverts it.
        """
        self._require_entity(tenant_id, company_id, entity_type)

        accepted = accepted_field_names(entity_type)
        required = required_field_names(entity_type)
        seen: set = set()
        clean: List[MappingWriteRow] = []
        for row in rows:
            source_path = (row.source_path or "").strip()
            if not source_path:
                raise AutocountServiceError(
                    "A mapping row is missing its AutoCount source field."
                )
            if row.transform not in TRANSFORMS:
                raise AutocountServiceError(
                    f"'{row.transform}' is not a known transform."
                )
            target = row.sorento_field
            if target not in accepted:
                raise AutocountServiceError(
                    f"'{target}' is not a Sorento field accepted for "
                    f"{entity_type}. Choose one of: {', '.join(sorted(accepted))}."
                )
            if target in seen:
                raise AutocountServiceError(
                    f"The Sorento field '{target}' is mapped more than once."
                )
            seen.add(target)
            clean.append(MappingWriteRow(source_path, row.transform, target))

        # Replace only the deliverable rows; provenance rows survive.
        self.mappings.delete_by_canonical(tenant_id, company_id, entity_type, accepted)
        for order, row in enumerate(clean):
            self.mappings.add(
                AcFieldMapping(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    scope=SCOPE_HEADER,  # masters are header-only (plan 15 §2)
                    source_path=row.source_path,
                    canonical_field=row.sorento_field,
                    transform=row.transform,
                    is_required=row.sorento_field in required,
                    is_enabled=True,
                    sort_order=order,
                )
            )
        self.db.commit()
        return self._mapping_view(tenant_id, company_id, entity_type)
