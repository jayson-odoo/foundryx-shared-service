"""WhatsApp template management — build / submit / edit / delete / sync (plan 07).

Local-draft lifecycle (NOT the status engine, T1/T2): LOCAL_DRAFT → PENDING →
APPROVED/REJECTED/PAUSED/DISABLED, with Meta as system-of-record. Single
canonical store = Meta-shape `components_json`; the friendly doc is derived via
the parity-pinned transform. Tenant-scoped throughout. Dev-safe (T9) when
`credentials.dev`. Logger emits a `template.status_changed` seam (BL-109).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import DEFAULT_TENANT_ID
from app.services.storage import storage_for_tenant
from ..adapters.base import SendError
from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel, WhatsappTemplate
from ..schemas import TemplateDetail, TemplateManageItem
from ..security import decrypt_credentials
from ..template_schemas import (
    TEMPLATE_STATUSES,
    WaTemplateDoc,
    distinct_var_count,
    from_meta_components,
    to_meta_components,
    validate_doc,
)
from .message_service import template_body_text, template_variable_count

logger = logging.getLogger("omnichannel.templates")

# Statuses whose components may be edited (re-submits to PENDING on save, T7).
_EDIT_RESUBMIT = {"APPROVED", "REJECTED", "PAUSED"}
# Statuses whose components are fully editable in place (no Meta call).
_EDIT_LOCAL = {"LOCAL_DRAFT"}
# Statuses where editing is blocked entirely.
_EDIT_BLOCKED = {"PENDING", "DISABLED"}


class TemplateNotFound(Exception):
    pass


class TemplateManagementService:
    def __init__(self, db: Session):
        self.db = db

    # ── helpers ──────────────────────────────────────────────────────────────
    def _channel(self, channel_id: str, tenant_id: str) -> Channel:
        c = (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id == channel_id)
            .first()
        )
        if c is None:
            raise TemplateNotFound()
        return c

    def _row(self, channel_id: str, template_id: str, tenant_id: str) -> WhatsappTemplate:
        t = (
            self.db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.tenant_id == tenant_id,
                WhatsappTemplate.channel_id == channel_id,
                WhatsappTemplate.id == template_id,
            )
            .first()
        )
        if t is None:
            raise TemplateNotFound()
        return t

    def _credentials(self, c: Channel) -> dict:
        return decrypt_credentials(c.credentials_json) if c.credentials_json else {}

    def _adapter(self, c: Channel):
        """A channel adapter instrumented to log ``graph:template_submit`` rows to
        the Developers → Logs console (sprint-4/12 Slice 2)."""
        from .activity import build_meta_recorder

        return get_adapter(
            c.channel_type,
            recorder=build_meta_recorder(self.db, c.tenant_id, c.workspace_id),
        )

    def _is_dev(self, creds: dict) -> bool:
        return bool(creds.get("dev")) or not settings.meta_app_id

    def _item(self, t: WhatsappTemplate) -> TemplateManageItem:
        body = template_body_text(t.components_json)
        return TemplateManageItem(
            id=t.id,
            channelId=t.channel_id,
            name=t.name,
            language=t.language,
            category=t.category,
            status=t.status or "LOCAL_DRAFT",
            quality=t.quality,
            rejectedReason=t.rejected_reason,
            bodyPreview=body,
            variableCount=template_variable_count(body),
            metaTemplateId=t.meta_template_id,
            lastSyncedAt=t.last_synced_at,
            createdAt=t.created_at,
        )

    def _detail(self, t: WhatsappTemplate) -> TemplateDetail:
        components = t.components_json or []
        doc = from_meta_components(
            components, name=t.name, category=t.category or "UTILITY", language=t.language or "en",
        )
        base = self._item(t)
        return TemplateDetail(**base.model_dump(by_alias=False), doc=doc.model_dump(), components=components)

    def _existing_names(self, channel_id: str, tenant_id: str, *, exclude_id: Optional[str] = None) -> set:
        q = self.db.query(WhatsappTemplate.name).filter(
            WhatsappTemplate.tenant_id == tenant_id, WhatsappTemplate.channel_id == channel_id
        )
        if exclude_id:
            q = q.filter(WhatsappTemplate.id != exclude_id)
        return {n for (n,) in q.all()}

    # ── reads ────────────────────────────────────────────────────────────────
    def list(
        self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID, *,
        page: int = 0, page_size: int = 25, search: Optional[str] = None,
        status_filter: Optional[str] = None, category: Optional[str] = None,
        language: Optional[str] = None, sort_by: Optional[str] = None, sort_dir: str = "asc",
    ) -> Tuple[List[TemplateManageItem], int]:
        self._channel(channel_id, tenant_id)
        q = self.db.query(WhatsappTemplate).filter(
            WhatsappTemplate.tenant_id == tenant_id, WhatsappTemplate.channel_id == channel_id
        )
        if search and search.strip():
            q = q.filter(WhatsappTemplate.name.ilike(f"%{search.strip()}%"))
        if status_filter:
            q = q.filter(WhatsappTemplate.status == status_filter)
        if category:
            q = q.filter(WhatsappTemplate.category == category)
        if language:
            q = q.filter(WhatsappTemplate.language == language)
        total = q.count()
        sort_col = {
            "name": WhatsappTemplate.name,
            "status": WhatsappTemplate.status,
            "category": WhatsappTemplate.category,
            "created": WhatsappTemplate.created_at,
        }.get(sort_by or "", WhatsappTemplate.created_at)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc(), WhatsappTemplate.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return [self._item(t) for t in rows], total

    def get(self, channel_id: str, template_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> TemplateDetail:
        self._channel(channel_id, tenant_id)
        return self._detail(self._row(channel_id, template_id, tenant_id))

    # ── writes ───────────────────────────────────────────────────────────────
    def save_draft(self, channel_id: str, doc: WaTemplateDoc, tenant_id: str = DEFAULT_TENANT_ID) -> TemplateDetail:
        self._channel(channel_id, tenant_id)
        validate_doc(doc, existing_names=self._existing_names(channel_id, tenant_id))
        row = WhatsappTemplate(
            tenant_id=tenant_id, channel_id=channel_id, name=doc.name,
            language=doc.language, category=doc.category,
            components_json=to_meta_components(doc), status="LOCAL_DRAFT",
            media_sample_key=doc.header.sampleKey if doc.header and doc.header.format != "TEXT" else None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._detail(row)

    def edit(self, channel_id: str, template_id: str, doc: WaTemplateDoc, tenant_id: str = DEFAULT_TENANT_ID) -> TemplateDetail:
        self._channel(channel_id, tenant_id)
        t = self._row(channel_id, template_id, tenant_id)
        cur_status = t.status or "LOCAL_DRAFT"
        if cur_status in _EDIT_BLOCKED:
            raise HTTPException(status.HTTP_409_CONFLICT, "This template can't be edited in its current state.")
        validate_doc(doc, existing_names=self._existing_names(channel_id, tenant_id, exclude_id=template_id))
        t.name = doc.name
        t.language = doc.language
        t.category = doc.category
        t.components_json = to_meta_components(doc)
        t.media_sample_key = doc.header.sampleKey if doc.header and doc.header.format != "TEXT" else None
        if cur_status in _EDIT_RESUBMIT:
            # Synced template edited → re-enters Meta review.
            ch = self._channel(channel_id, tenant_id)
            creds = self._credentials(ch)
            if not self._is_dev(creds) and t.meta_template_id:
                payload = self._submit_payload(t, doc, creds, channel_id, tenant_id)
                self._adapter(ch).edit_template(creds, t.meta_template_id, payload)
            t.status = "PENDING"
            t.rejected_reason = None
        # LOCAL_DRAFT stays LOCAL_DRAFT.
        self.db.commit()
        self.db.refresh(t)
        return self._detail(t)

    def _submit_payload(self, t: WhatsappTemplate, doc: WaTemplateDoc, creds: dict, channel_id: str, tenant_id: str) -> dict:
        """Build the Meta create/edit payload, resolving a media-header sample to
        a resumable-upload handle (T10)."""
        components = to_meta_components(doc)
        if doc.header and doc.header.format != "TEXT" and t.media_sample_key:
            handle = self._upload_sample(t.media_sample_key, creds, tenant_id)
            for comp in components:
                if comp.get("type") == "HEADER" and comp.get("format") != "TEXT":
                    comp["example"] = {"header_handle": [handle]}
        return {
            "name": doc.name,
            "category": doc.category,
            "language": doc.language,
            "components": components,
        }

    def _upload_sample(self, media_key: str, creds: dict, tenant_id: str) -> str:
        adapter = get_adapter("WHATSAPP")
        file_bytes = b""
        mime = "application/octet-stream"
        if not self._is_dev(creds):
            try:
                kind, value = storage_for_tenant(self.db, tenant_id).resolve(media_key)
                if kind == "path":
                    with open(value, "rb") as fh:
                        file_bytes = fh.read()
            except Exception:  # storage hiccup must not 500 a submit (GP-5)
                file_bytes = b""
        return adapter.upload_resumable(creds, settings.meta_app_id, file_bytes, mime)

    def submit(self, channel_id: str, template_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> TemplateDetail:
        channel = self._channel(channel_id, tenant_id)
        t = self._row(channel_id, template_id, tenant_id)
        if (t.status or "LOCAL_DRAFT") != "LOCAL_DRAFT":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a local draft can be submitted.")
        doc = from_meta_components(t.components_json, name=t.name, category=t.category or "UTILITY", language=t.language or "en")
        validate_doc(doc, existing_names=self._existing_names(channel_id, tenant_id, exclude_id=template_id))
        creds = self._credentials(channel)
        payload = self._submit_payload(t, doc, creds, channel_id, tenant_id)
        try:
            result = self._adapter(channel).create_template(creds, channel.waba_id or "", payload)
        except SendError as exc:
            # Meta rejected the template = client-fixable input → 422, NOT 5xx.
            # Cloudflare replaces any origin 5xx body with its own error page, so
            # a 502 hid Meta's actual reason from the operator; a 4xx passes the
            # detail straight through (mirrors how send/react surface SendError).
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        t.meta_template_id = result.get("meta_template_id")
        t.status = (result.get("status") or "PENDING").upper()
        t.rejected_reason = None
        self.db.commit()
        self.db.refresh(t)
        return self._detail(t)

    def delete(self, channel_id: str, template_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        channel = self._channel(channel_id, tenant_id)
        t = self._row(channel_id, template_id, tenant_id)
        if (t.status or "LOCAL_DRAFT") != "LOCAL_DRAFT":
            creds = self._credentials(channel)
            if not self._is_dev(creds):
                try:
                    get_adapter(channel.channel_type).delete_template(
                        creds, channel.waba_id or "", t.name, t.meta_template_id
                    )
                except SendError as exc:
                    # 4xx so Cloudflare passes Meta's reason through (see submit).
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        self.db.delete(t)
        self.db.commit()

    def sync(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Tuple[List[TemplateManageItem], int]:
        channel = self._channel(channel_id, tenant_id)
        creds = self._credentials(channel)
        now = datetime.now(timezone.utc)
        if self._is_dev(creds):
            # Dev shortcut (T9): promote local PENDING → APPROVED (simulates review).
            for t in self.db.query(WhatsappTemplate).filter(
                WhatsappTemplate.tenant_id == tenant_id,
                WhatsappTemplate.channel_id == channel_id,
                WhatsappTemplate.status == "PENDING",
            ):
                t.status = "APPROVED"
                t.quality = t.quality or "GREEN"
                t.last_synced_at = now
            self.db.commit()
            return self.list(channel_id, tenant_id)

        fetched = get_adapter(channel.channel_type).list_templates(creds, channel.waba_id or "")
        by_meta = {}
        by_name = {}
        for t in self.db.query(WhatsappTemplate).filter(
            WhatsappTemplate.tenant_id == tenant_id, WhatsappTemplate.channel_id == channel_id
        ):
            if t.meta_template_id:
                by_meta[t.meta_template_id] = t
            by_name[(t.name, t.language)] = t
        for raw in fetched:
            mid = str(raw.get("id")) if raw.get("id") is not None else None
            row = by_meta.get(mid) or by_name.get((raw.get("name"), raw.get("language")))
            if row is None:
                row = WhatsappTemplate(
                    tenant_id=tenant_id, channel_id=channel_id,
                    name=raw.get("name") or "", language=raw.get("language"),
                )
                self.db.add(row)
            row.meta_template_id = mid or row.meta_template_id
            row.category = raw.get("category") or row.category
            row.status = (raw.get("status") or row.status or "").upper() or row.status
            qscore = raw.get("quality_score")
            if isinstance(qscore, dict):
                row.quality = (qscore.get("score") or "").upper() or row.quality
            row.components_json = raw.get("components") or row.components_json
            row.last_synced_at = now
        self.db.commit()
        return self.list(channel_id, tenant_id)

    # ── webhook application (plan 07 §4) ─────────────────────────────────────
    def apply_webhook_event(self, channel: Channel, event: dict) -> bool:
        """Update the matching local row from a template_* webhook. Idempotent.
        Returns True if a row was updated. Never raises on a malformed payload."""
        try:
            mid = event.get("message_template_id")
            name = event.get("name")
            language = event.get("language")
            q = self.db.query(WhatsappTemplate).filter(
                WhatsappTemplate.tenant_id == channel.tenant_id,
                WhatsappTemplate.channel_id == channel.id,
            )
            row = None
            if mid:
                row = q.filter(WhatsappTemplate.meta_template_id == str(mid)).first()
            if row is None and name:
                nq = q.filter(WhatsappTemplate.name == name)
                # Only constrain by language when the webhook actually supplied
                # one — `== None` would render IS NULL and miss real rows.
                if language:
                    nq = nq.filter(WhatsappTemplate.language == language)
                row = nq.first()
            if row is None:
                return False
            kind = event.get("kind")
            if kind == "template_status" and event.get("status"):
                new_status = event["status"].upper()
                # Normalise Meta's event names onto our local status set so the
                # row never holds a value the badge/filters don't know.
                norm = {
                    "FLAGGED": "PAUSED",
                    "PENDING_DELETION": "DISABLED",
                    "DELETED": "DISABLED",
                    "REINSTATED": "APPROVED",
                }.get(new_status, new_status)
                if norm not in TEMPLATE_STATUSES:
                    norm = "DISABLED"
                row.status = norm
                row.rejected_reason = event.get("reason") if row.status == "REJECTED" else None
            elif kind == "template_quality" and event.get("quality"):
                row.quality = str(event["quality"]).upper()
            elif kind == "template_category" and event.get("category"):
                row.category = str(event["category"]).upper()
            self.db.commit()
            logger.info("template.status_changed channel=%s template=%s kind=%s", channel.id, row.id, kind)
            return True
        except Exception:  # webhook payloads are attacker-controllable — never crash the pipeline
            logger.exception("apply_webhook_event failed")
            self.db.rollback()
            return False
