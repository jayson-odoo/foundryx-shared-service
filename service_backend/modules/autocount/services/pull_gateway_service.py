"""Sprint-5/10 S4 - the public gateway's business logic (AC-10-29/30/31/32/
33), sitting on top of the S3 snapshot store. The router
(``routers/pull_v1.py``) stays HTTP + Pydantic-shape-only: every DB touch and
every business decision (company/entity/delivery-mode resolution, the error
ladder) lives here, raising ``PullGatewayError`` - never an HTTPException -
so the router's ONE translator renders the flat Appendix A6 envelope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from ..canonical.masters import ENTITY_PRODUCT
from ..models import (
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    PULL_SNAPSHOT_STATUS_BUILDING,
    PULL_SNAPSHOT_STATUS_FAILED,
    PULL_SNAPSHOT_STATUS_READY,
    AcCompany,
    AcPullApiKey,
    AcPullAudit,
    AcPullSnapshot,
)
from ..pull_auth import PullGatewayError
from ..repositories import (
    CompanyRepository,
    EntityConfigRepository,
    PullAuditRepository,
    PullSnapshotRepository,
)
from .company_service import CompanyNotFound
from .pull_service import (
    MAX_PULL_PAGE_SIZE,
    PullBuildCooldownError,
    PullPushActiveError,
    PullService,
)

# entity=`products`/`stock_balances` on the wire (Appendix A2), translated by
# ONE map to the internal canonical keys (AC-10-29). `stock_balance` has no
# module constant yet (lands with S5b's `ENTITY_STOCK_BALANCE`) - the wire
# name is fixed by Appendix A4 today, so the literal is safe to hardcode
# ahead of that slice.
ENTITY_WIRE_TO_INTERNAL: Dict[str, str] = {
    "products": ENTITY_PRODUCT,
    "stock_balances": "stock_balance",
}
ENTITY_INTERNAL_TO_WIRE: Dict[str, str] = {v: k for k, v in ENTITY_WIRE_TO_INTERNAL.items()}

_PULL_NOT_ENABLED_MESSAGE = (
    "This book/entity was never enabled for pull, or is not active."
)

# AC-10-58 M1 (security round, sprint-5/10 S6) - the PUBLIC `failed` header's
# ``error.message`` is a FIXED sentence per ``error_code``, never
# ``snapshot.error``. The stored text is written for an operator and names
# this deployment's own internals (the source host and port, an endpoint
# path, a driver message); the gateway's reader is a THIRD PARTY holding an
# API key. The code is what a consumer branches on (Appendix A6), so it stays
# verbatim - only the prose is replaced. The operator header
# (``pull_service.snapshot_header``) and ``integration_activity`` keep the
# full text, which is where a support engineer looks. Keyed by the literal
# code (never an import of ``..sync``, which imports the services package
# back); ``test_s10_s6_security_fixes.py`` pins this map against
# ``sync.PULL_SNAPSHOT_FAILED_CODES`` so a new code cannot drift in unmapped.
GATEWAY_FAILED_MESSAGES: Dict[str, str] = {
    "SOURCE_PAGE_FAILED": (
        "The source system did not return a usable page for this book. "
        "Contact the data owner."
    ),
    "EMPTY_EXTRACT": "The source system returned no rows for this book and entity.",
    "ENRICH_FAILED": (
        "A lookup this entity depends on did not return usable data. "
        "Contact the data owner."
    ),
    "ROW_LIMIT": "This entity holds more rows than one snapshot may carry.",
    "BUILD_ABANDONED": (
        "The build stopped before it finished. Request a new snapshot."
    ),
    "COMBINE_RULE_FAILED": (
        "A configured rule could not be applied to this data. "
        "Contact the data owner."
    ),
}
GATEWAY_FAILED_FALLBACK_MESSAGE = (
    "This snapshot could not be built. Contact the data owner."
)


def gateway_failed_message(error_code: Optional[str]) -> str:
    """The one operator-safe sentence for a failed snapshot's code. An
    unmapped/absent code (a future build failure this map has not learned
    yet) falls back to the generic sentence - it NEVER falls back to the
    stored text, which is the whole point of the map."""
    return GATEWAY_FAILED_MESSAGES.get(error_code or "", GATEWAY_FAILED_FALLBACK_MESSAGE)


def translate_entity_wire(wire: str) -> Optional[str]:
    return ENTITY_WIRE_TO_INTERNAL.get(wire)


def translate_entity_internal(internal: str) -> str:
    return ENTITY_INTERNAL_TO_WIRE.get(internal, internal)


def _iso_z(value: Optional[datetime]) -> Optional[str]:
    """Mirrors ``ApiModel``'s own Z-suffix serializer - this header is built
    as a raw dict (never through a Pydantic response model), because the
    OMISSION rules (AC-10-32: a `building`/`failed` header carries NONE of
    the `ready`-only keys, not even as `null`) need per-status key presence
    a fixed schema with defaults cannot express without also defaulting
    `recordCount`/`complete` to 0/False (the exact bug the kill test
    guards)."""
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
        timezone.utc
    )
    return aware.isoformat().replace("+00:00", "Z")


def gateway_snapshot_header(snapshot: AcPullSnapshot) -> Dict[str, Any]:
    """The PUBLIC gateway's own header shape (Appendix A3) - distinct from
    the operator route's ``pull_service.snapshot_header``/``PullSnapshotOut``
    (internal ids, always-present defaulted counters). Every key here is one
    Appendix A names for THIS status, and no other."""
    header: Dict[str, Any] = {
        "snapshotId": snapshot.id,
        "entity": translate_entity_internal(snapshot.entity_type),
        "companyCode": snapshot.company_code,
        "status": snapshot.status,
    }
    metadata = snapshot.metadata_json or {}
    if snapshot.status == PULL_SNAPSHOT_STATUS_READY:
        header.update(
            {
                "extractedAt": _iso_z(snapshot.extracted_at),
                "expiresAt": _iso_z(snapshot.expires_at),
                "recordCount": snapshot.record_count,
                "complete": snapshot.complete,
                "contentHash": snapshot.content_hash,
                "sourcePageSize": metadata.get("sourcePageSize"),
                "excludedCount": metadata.get("excludedCount", 0),
                "excludedRows": metadata.get("excludedRows", []),
            }
        )
        for key in (
            "zeroListPriceCount",
            "negativeListPriceCount",
            "enrichMissCount",
            "zeroPairs",
            "negativePairs",
            "fractionalPairs",
            "excludedNonzeroCount",
            "negativePairList",
        ):
            if key in metadata:
                header[key] = metadata[key]
    elif snapshot.status == PULL_SNAPSHOT_STATUS_FAILED:
        # AC-10-58 M1 - the CODE is the contract, the prose is fixed per code
        # (see ``GATEWAY_FAILED_MESSAGES``); ``snapshot.error`` itself never
        # reaches this surface.
        header["error"] = {
            "code": snapshot.error_code,
            "message": gateway_failed_message(snapshot.error_code),
        }
    return header


def write_pull_audit(
    db: Session,
    *,
    tenant_id: str,
    key_id: Optional[str],
    company_id: Optional[str],
    entity_type: Optional[str],
    snapshot_id: Optional[str],
    action: str,
    page: Optional[int],
    record_count: Optional[int],
    status_code: int,
) -> None:
    """AC-10-34's ONE write - key id, tenant, company, entity, snapshot,
    route/action, page, record count, outcome code, timestamp. NO payload
    field, NO plaintext key, no customer data - ever."""
    PullAuditRepository(db).add(
        AcPullAudit(
            tenant_id=tenant_id,
            key_id=key_id,
            company_id=company_id,
            entity_type=entity_type,
            snapshot_id=snapshot_id,
            action=action,
            page=page,
            record_count=record_count,
            status_code=status_code,
        )
    )


class PullGatewayService:
    def __init__(self, db: Session):
        self.db = db

    # ── build (POST /snapshots, AC-10-29/30/31) ─────────────────────────

    def build(
        self, key_row: AcPullApiKey, company_code_raw: str, internal_entity: str
    ) -> Tuple[AcCompany, AcPullSnapshot]:
        # Security round 1 LOW 7 - ALL matches, never pick one arbitrarily.
        # `set_sink_target` does not (yet) prevent two companies in one
        # tenant from sharing a code (backlogged, not fixed in this slice -
        # existing data unknown), so the gateway itself must refuse rather
        # than silently resolve a DB-order-dependent "first" row.
        matches = CompanyRepository(self.db).find_by_sorento_company_code(
            key_row.tenant_id, company_code_raw
        )
        if not matches:
            raise PullGatewayError(
                404, "UNKNOWN_COMPANY", "No company with that code for this key."
            )
        if len(matches) > 1:
            raise PullGatewayError(
                409, "AMBIGUOUS_COMPANY",
                "More than one company in this tenant shares that code.",
            )
        company = matches[0]
        if company.id not in (key_row.company_ids or []):
            raise PullGatewayError(
                403, "COMPANY_NOT_ALLOWED",
                "This company is not in this key's allowed scope.",
                company_id=company.id,
            )

        config = EntityConfigRepository(self.db).get(
            key_row.tenant_id, company.id, internal_entity
        )
        if config is None:
            raise PullGatewayError(
                409, "PULL_NOT_ENABLED", _PULL_NOT_ENABLED_MESSAGE, company_id=company.id
            )
        if config.delivery_mode == DELIVERY_MODE_PUSH:
            if config.etl_status == ETL_STATUS_ACTIVE:
                raise PullGatewayError(
                    409, "PUSH_ACTIVE", "This book is now automatic.",
                    company_id=company.id,
                )
            raise PullGatewayError(
                409, "PULL_NOT_ENABLED", _PULL_NOT_ENABLED_MESSAGE, company_id=company.id
            )
        if config.etl_status != ETL_STATUS_ACTIVE:
            raise PullGatewayError(
                409, "PULL_NOT_ENABLED", _PULL_NOT_ENABLED_MESSAGE, company_id=company.id
            )

        try:
            snapshot = PullService(self.db).request_build(
                key_row.tenant_id, company.id, internal_entity,
                requested_via="gateway", requested_by=None,
            )
        except PullBuildCooldownError as exc:
            raise PullGatewayError(
                429, "TOO_MANY_BUILDS",
                "A build was requested for this book/entity less than 60 seconds ago.",
                company_id=company.id,
            ).with_retry_after(exc.retry_after_seconds)
        except PullPushActiveError:
            # review round 2 (item 4) - the gateway's OWN pre-check above
            # already refuses a push-active pair before ever calling
            # ``request_build``, so this branch is defence in depth (the
            # SERVICE guard is now authoritative for both callers) rather
            # than the primary path for this route.
            raise PullGatewayError(
                409, "PUSH_ACTIVE", "This book is now automatic.",
                company_id=company.id,
            )
        except CompanyNotFound:
            # Security round 1 HIGH 1 - a TOCTOU race (the company vanished
            # between our own resolution above and this call's internal
            # re-fetch): the contract's own 404, never a bare 500.
            raise PullGatewayError(
                404, "UNKNOWN_COMPANY", "No company with that code for this key."
            )
        return company, snapshot

    # ── reads (GET /snapshots/{id}[/rows], AC-10-30/32/33) ──────────────

    def get_snapshot_for_key(self, key_row: AcPullApiKey, snapshot_id: str) -> AcPullSnapshot:
        """Tenant AND full-company-SET scoped (a key may name more than one
        company) - possession of an id is not authorisation (AC-10-30/47).
        An id outside that scope reads IDENTICALLY to an unknown one."""
        snapshot = PullSnapshotRepository(self.db).get_for_key_scope(
            key_row.tenant_id, key_row.company_ids, snapshot_id
        )
        if snapshot is None:
            raise PullGatewayError(404, "UNKNOWN_SNAPSHOT", "Unknown snapshot, or not yours.")
        self._ensure_not_expired(snapshot)
        return snapshot

    def snapshot_progress(
        self, key_row: AcPullApiKey, snapshot: AcPullSnapshot
    ) -> Optional[Dict[str, Any]]:
        """sprint-5/11 S5 (AC-11-41) - the public gateway `building` header's
        `progress`, gated on THIS snapshot's own status before delegating to
        the shared projection living next to the preview job's own rule
        (``preview_job_service.snapshot_job_progress``). Resolved WITH
        ``key_row.tenant_id`` (never the snapshot's own, though they always
        agree once ``get_snapshot_for_key`` has already scoped it) - the
        SAME tenant every other gateway read is scoped by."""
        if snapshot.status != PULL_SNAPSHOT_STATUS_BUILDING:
            return None
        from .preview_job_service import snapshot_job_progress

        return snapshot_job_progress(self.db, key_row.tenant_id, snapshot.job_id)

    def _ensure_not_expired(self, snapshot: AcPullSnapshot) -> None:
        if snapshot.expires_at is not None and snapshot.expires_at <= datetime.now(timezone.utc):
            raise PullGatewayError(
                410, "SNAPSHOT_EXPIRED", "This snapshot has expired. Build a fresh one.",
                company_code=snapshot.company_code,
                entity=translate_entity_internal(snapshot.entity_type),
                snapshot_id=snapshot.id, company_id=snapshot.company_id,
                entity_type=snapshot.entity_type,
            )

    def rows_page(
        self, snapshot: AcPullSnapshot, *, page: int, page_size: int
    ) -> Tuple[list, int, int]:
        clamped_size = min(max(page_size, 1), MAX_PULL_PAGE_SIZE)
        rows, total = PullSnapshotRepository(self.db).rows_page(
            snapshot.tenant_id, snapshot.id, page=max(page, 1), page_size=clamped_size
        )
        return rows, total, clamped_size
