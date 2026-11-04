"""Contact erase (plan 56 C, PDPA): ONE service behind the API-key route and the
staff route.

Rows go in ONE transaction, in a fixed order (no foreign key cascades exist):
parked workflow waits cancelled first, then message reactions, messages (notes
included), conversation events, channel identities, tag links, waits, workflow
contact fires, broadcast recipient rows and the id in broadcast audiences,
respond.io migration refs (the contact ref is kept as a tombstone), the ideation
submitter link (through a capability, set to NULL), webhook delivery payloads
reduced to ids, and last the contact. Stored files are deleted AFTER the commit
by a retrying task; a failed file delete never undoes the erase.

Every id is resolved with the tenant (and the workspace for the contact)."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from ..repositories.contact_erase_repository import (
    ENTITY_CONTACT,
    ContactEraseRepository,
    local_key_from_url,
)
from . import realtime

logger = logging.getLogger("foundryx.omnichannel.erase")

EVENT_CONTACT_ERASED = "contact.erased"
IDEATION_CLEANUP_CAPABILITY = "contact.erase_cleanup"
_REF_ENTITIES_TO_DELETE = ("identity", "message", "event")
_ENVELOPE_KEYS = ("id", "type", "workspaceId", "channelId", "occurredAt")


class ContactNotFound(Exception):
    """No such contact in this tenant and workspace (a uniform 404)."""


@dataclass
class EraseResult:
    contact_id: str
    erased_at: datetime
    messages: int
    files: int


def _wire(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _names_contact(payload: Dict[str, Any], contact_id: str) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    contact = data.get("contact")
    message = data.get("message")
    return (
        data.get("contactId") == contact_id
        or (isinstance(contact, dict) and contact.get("id") == contact_id)
        or (isinstance(message, dict) and message.get("contactId") == contact_id)
    )


def _ids_only(payload: Dict[str, Any], contact_id: str) -> Dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message = data.get("message")
    message_id = data.get("messageId") or (message.get("id") if isinstance(message, dict) else None)
    reduced: Dict[str, Any] = {k: payload[k] for k in _ENVELOPE_KEYS if k in payload}
    new_data: Dict[str, Any] = {"contactId": contact_id}
    if isinstance(message_id, str) and message_id:
        new_data["messageId"] = message_id
    reduced["data"] = new_data
    return reduced


class ContactEraseService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactEraseRepository(db)

    def erase_in_tenant(self, tenant_id: str, contact_id: str) -> EraseResult:
        """Staff path: the contact is resolved by tenant, its own workspace is
        then used for every workspace-scoped step."""
        contact = self.repo.get_contact_in_tenant(contact_id, tenant_id)
        if contact is None:
            raise ContactNotFound()
        return self.erase(tenant_id, contact.workspace_id, contact.id)

    def erase(self, tenant_id: str, workspace_id: str, contact_id: str) -> EraseResult:
        contact = self.repo.get_contact(contact_id, tenant_id, workspace_id)
        if contact is None:
            raise ContactNotFound()
        erased_at = datetime.now(timezone.utc)
        try:
            messages, keys = self._erase_rows(tenant_id, workspace_id, contact_id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        result = EraseResult(contact_id, erased_at, messages, len(keys))
        self._after_commit(tenant_id, workspace_id, result, sorted(keys))
        return result

    # ── one transaction ──────────────────────────────────────────────────────
    def _erase_rows(self, tenant_id: str, workspace_id: str, contact_id: str):
        repo = self.repo
        msgs = repo.messages(contact_id, tenant_id)
        message_ids = [m[0] for m in msgs]
        keys: Set[str] = set()
        for _mid, media_key, media_url in msgs:
            if media_key:
                keys.add(media_key)
            legacy = local_key_from_url(media_url)
            if legacy:
                keys.add(legacy)
        event_ids = repo.event_ids(contact_id, tenant_id)
        identity_ids = repo.identity_ids(contact_id, tenant_id)

        self._cancel_waits(tenant_id, contact_id)
        repo.delete_reactions(message_ids, tenant_id)
        repo.delete_messages(contact_id, tenant_id)
        repo.delete_events(contact_id, tenant_id)
        repo.delete_identities(contact_id, tenant_id)
        repo.delete_tag_links(contact_id, tenant_id)
        repo.delete_waits(contact_id, tenant_id)
        repo.delete_fires(contact_id, tenant_id)
        repo.delete_recipients(contact_id, tenant_id)
        repo.drop_from_audiences(contact_id, tenant_id, workspace_id)
        self._migration_refs(tenant_id, workspace_id, contact_id, message_ids + event_ids + identity_ids)
        self._ideation_cleanup(tenant_id, contact_id)
        self._reduce_deliveries(tenant_id, workspace_id, contact_id)
        repo.flush()
        repo.delete_contact(contact_id, tenant_id, workspace_id)
        repo.flush()
        return len(message_ids), keys

    def _cancel_waits(self, tenant_id: str, contact_id: str) -> None:
        from app.workflow_engine.parking import cancel_parked_run

        for wait in self.repo.waits(contact_id, tenant_id):
            cancel_parked_run(
                self.db, wait.run_id, tenant_id, reason="The contact was erased."
            )

    def _migration_refs(
        self, tenant_id: str, workspace_id: str, contact_id: str, child_ids: List[str]
    ) -> None:
        for ref in self.repo.migration_refs(tenant_id, workspace_id, [contact_id] + child_ids):
            if ref.entity_type == ENTITY_CONTACT and ref.local_id == contact_id:
                self.repo.tombstone_ref(ref)
            elif ref.entity_type in _REF_ENTITIES_TO_DELETE:
                self.repo.delete_ref(ref)

    def _ideation_cleanup(self, tenant_id: str, contact_id: str) -> None:
        from app.module_platform.capabilities import resolve_capability

        handler = resolve_capability(self.db, tenant_id, IDEATION_CLEANUP_CAPABILITY, 1)
        if handler is not None:
            handler(self.db, tenant_id, {"contactId": contact_id})

    def _reduce_deliveries(self, tenant_id: str, workspace_id: str, contact_id: str) -> None:
        for row in self.repo.deliveries_naming(contact_id, tenant_id):
            payload = row.payload_json
            if not isinstance(payload, dict) or not _names_contact(payload, contact_id):
                continue
            if payload.get("workspaceId") not in (None, workspace_id):
                continue
            row.payload_json = _ids_only(payload, contact_id)  # fresh dict: JSON column

    # ── after the commit ─────────────────────────────────────────────────────
    def _after_commit(
        self, tenant_id: str, workspace_id: str, result: EraseResult, keys: List[str]
    ) -> None:
        try:
            realtime.publish(workspace_id, {"type": "contact.erased", "contactId": result.contact_id})
        except Exception:  # noqa: BLE001 - realtime never breaks an erase
            logger.warning("realtime publish failed after a contact erase")
        try:
            from .webhook_delivery import enqueue_workspace_event

            enqueue_workspace_event(
                self.db,
                tenant_id,
                workspace_id,
                EVENT_CONTACT_ERASED,
                f"{result.contact_id}:erased",
                {"contactId": result.contact_id, "erasedAt": _wire(result.erased_at)},
            )
        except Exception:  # noqa: BLE001
            logger.warning("contact.erased webhook fan-out failed")
        if keys:
            try:
                from ..worker import purge_erased_files

                purge_erased_files.delay(tenant_id, keys)
            except Exception:  # noqa: BLE001 - a file delete never undoes the erase
                logger.warning("erased-file purge could not run (%d files)", len(keys))


def purge_files(tenant_id: str, keys: List[str]) -> None:
    """Delete stored files by key. A missing file counts as deleted. Raises one
    generic error after trying every key when any delete failed, so the task
    retries; nothing about a file or contact is logged or raised."""
    from app.services import storage as storage_module

    failed = 0
    for key in keys:
        connection = key.split(":", 2)[1] if key.startswith("conn:") and key.count(":") >= 2 else "local"
        try:
            _delete_one(storage_module, tenant_id, key)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.warning("erased-file delete failed (connection %s)", connection)
    if failed:
        raise RuntimeError(f"{failed} erased file(s) could not be deleted")


def _delete_one(storage_module, tenant_id: str, key: str) -> None:
    override = storage_module._storage
    if override is not None:
        override.delete(key)
    elif key.startswith("conn:"):
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            storage_module.storage_for_tenant(db, tenant_id).delete(key)
        finally:
            db.close()
    else:
        storage_module.LocalDiskStorage().delete(key)
