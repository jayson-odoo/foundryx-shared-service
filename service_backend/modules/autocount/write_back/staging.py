"""Stage a wrapper document and push it (plan 55 S4; shared by the write flow
and the day pull).

The raw document is upserted by ``source_ref`` first (a verified write or a
pulled document is never lost to a mapping or sink fault); then, unless the
entity is SQL-sourced, it is mapped through ``map_wrapper_document`` and
pushed once. Any fault after staging leaves the row STAGED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    STAGED,
    STAGED_PUSHED,
    AcCompany,
    AcStagedRecord,
)
from modules.autocount.write_back.doc_mapping import (
    ENTITY_BY_KIND,
    WrapperMappingError,
    map_wrapper_document,
)
from modules.autocount.write_back.repository import (
    EntitySourceRepository,
    StagedDocRepository,
)

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]
SinkFactory = Callable[..., Any]
STAGING_JOB_ID = "write-back"


@dataclass(frozen=True)
class StageOutcome:
    staged: bool
    pushed: bool


class DocStager:
    def __init__(self, db: Session, sink_factory: Optional[SinkFactory] = None) -> None:
        self.db = db
        self.staged = StagedDocRepository(db)
        self._sink_factory = sink_factory or self._default_sink

    def stage_and_push(
        self, company: AcCompany, doc: Doc, kind: str, *, skip_unchanged: bool = False
    ) -> StageOutcome:
        """Never raises: the caller's own outcome (a verified write, a fetched
        day) must stand whatever happens here."""
        try:
            row, changed = self._stage_raw(company, doc, kind, skip_unchanged)
            self.db.commit()
            if not changed:
                return StageOutcome(False, False)
            return StageOutcome(True, self._push(company, doc, kind, row))
        except Exception:  # noqa: BLE001
            self.db.rollback()
            logger.exception("autocount write-back staging/push failed")
            return StageOutcome(False, False)

    def _stage_raw(
        self, company: AcCompany, doc: Doc, kind: str, skip_unchanged: bool
    ) -> "tuple[AcStagedRecord, bool]":
        from modules.autocount.sync import json_safe_row

        entity_type = ENTITY_BY_KIND[kind]
        raw = {k: v for k, v in doc.items() if k != "Details"}
        raw["_lines"] = list(doc.get("Details") or [])
        raw = json_safe_row(raw)
        ref = f"{company.database_name}:{doc.get('DocKey')}"
        row = self.staged.newest(company.tenant_id, company.id, entity_type, ref)
        if row is None:
            row = AcStagedRecord(
                tenant_id=company.tenant_id,
                company_id=company.id,
                entity_type=entity_type,
                job_id=STAGING_JOB_ID,
                source_ref=ref,
                doc_no=str(doc.get("DocNo") or ""),
                status=STAGED,
            )
            self.db.add(row)
        elif skip_unchanged and row.status == STAGED_PUSHED and row.raw_json == raw:
            return row, False
        row.raw_json = raw
        row.doc_no = str(doc.get("DocNo") or row.doc_no or "")
        row.canonical_json = None
        row.diff_json = None
        row.errors_json = None
        row.error = None
        row.status = STAGED
        row.pushed_at = None
        self.db.flush()
        return row, True

    def _push(self, company: AcCompany, doc: Doc, kind: str, row: AcStagedRecord) -> bool:
        from modules.autocount.sync import compute_diff

        entity_type = ENTITY_BY_KIND[kind]
        source = EntitySourceRepository(self.db).source_impl(
            company.tenant_id, company.id, entity_type
        )
        if source == SOURCE_IMPL_SQL_DB:
            return False  # SQL-sourced entity: refreshed through SQL, not here
        try:
            _entity, record = map_wrapper_document(
                self.db, tenant_id=company.tenant_id, company=company, doc=doc, kind=kind
            )
        except WrapperMappingError as exc:
            row.error = str(exc)[:4000]
            self.db.commit()
            return False
        canonical = record.comparable()
        row.diff_json = compute_diff(None, canonical)
        row.canonical_json = canonical
        row_id, tenant_id, company_id = row.id, company.tenant_id, company.id
        self.db.commit()  # no transaction open while the sink is called
        sink = self._sink_factory(tenant_id, company, entity_type)
        request_id = f"write-back:{row_id}"
        self.db.commit()
        result = sink.write(record, request_id=request_id)
        if getattr(result, "ok", True) is False:
            return False
        row = self.staged.newest(tenant_id, company_id, entity_type, f"{company.database_name}:{doc.get('DocKey')}") or row
        row.status = STAGED_PUSHED
        row.pushed_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def _default_sink(self, tenant_id: str, company: AcCompany, entity_type: str) -> Any:
        from modules.autocount.services.company_service import CompanyService

        return CompanyService(self.db).sink_for_company(tenant_id, company, entity_type)
