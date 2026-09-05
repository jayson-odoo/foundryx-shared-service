"""Contact tag registry - per-workspace tags + contact links (plan 25 S1/S2).

CRUD + case-insensitive per-workspace uniqueness + cap (500 tags, AC-CDM-09);
`replace_links` implements the `tagIds` PATCH contract (AC-CDM-10) - ids are
validated against the contact's OWN workspace before any write (polymorphic
stored-id rule: validated at save, resolved tenant + workspace scoped at
read), and the whole set is replaced, never merged. Deleting a tag removes its
links only (AC-CDM-11) - the contacts themselves are untouched.
"""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Contact, ContactTag, ContactTagLink

MAX_TAGS_PER_WORKSPACE = 500


class TagNotFound(Exception):
    pass


class TagValidationError(Exception):
    """Carries the offending field key (default `name`) - the router/caller
    turns this into a 422 `{fieldErrors}` body."""

    def __init__(self, message: str, field: str = "name"):
        super().__init__(message)
        self.message = message
        self.field = field


class ContactTagService:
    def __init__(self, db: Session):
        self.db = db

    # ── registry CRUD ────────────────────────────────────────────────────────
    def list(self, workspace_id: str, tenant_id: str) -> List[ContactTag]:
        return (
            self.db.query(ContactTag)
            .filter(ContactTag.tenant_id == tenant_id, ContactTag.workspace_id == workspace_id)
            .order_by(func.lower(ContactTag.name).asc())
            .all()
        )

    def get(self, tag_id: str, workspace_id: str, tenant_id: str) -> ContactTag:
        row = (
            self.db.query(ContactTag)
            .filter(
                ContactTag.id == tag_id,
                ContactTag.workspace_id == workspace_id,
                ContactTag.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise TagNotFound()
        return row

    def contacts_counts(self, workspace_id: str, tenant_id: str) -> Dict[str, int]:
        """Batched `tag_id -> attached-contact count` (list view + delete-
        confirmation copy, AC-CDM-32)."""
        rows = (
            self.db.query(ContactTagLink.tag_id, func.count(ContactTagLink.id))
            .join(ContactTag, ContactTag.id == ContactTagLink.tag_id)
            .filter(ContactTag.workspace_id == workspace_id, ContactTagLink.tenant_id == tenant_id)
            .group_by(ContactTagLink.tag_id)
            .all()
        )
        return {tag_id: count for tag_id, count in rows}

    def _find_by_name(self, workspace_id: str, tenant_id: str, name: str) -> Optional[ContactTag]:
        return (
            self.db.query(ContactTag)
            .filter(
                ContactTag.tenant_id == tenant_id,
                ContactTag.workspace_id == workspace_id,
                func.lower(ContactTag.name) == name.strip().lower(),
            )
            .first()
        )

    def create(self, workspace_id: str, tenant_id: str, payload) -> ContactTag:
        name = (payload.name or "").strip()
        if not name:
            raise TagValidationError("Name is required.", "name")
        if self._find_by_name(workspace_id, tenant_id, name) is not None:
            raise TagValidationError("A tag with this name already exists.", "name")
        count = (
            self.db.query(ContactTag.id)
            .filter(ContactTag.tenant_id == tenant_id, ContactTag.workspace_id == workspace_id)
            .count()
        )
        if count >= MAX_TAGS_PER_WORKSPACE:
            raise TagValidationError(
                f"This workspace already has {MAX_TAGS_PER_WORKSPACE} tags (the maximum).", "name"
            )
        row = ContactTag(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            emoji=(payload.emoji or None),
            color=(payload.color or None),
            description=(payload.description or None),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, tag_id: str, workspace_id: str, tenant_id: str, payload) -> ContactTag:
        row = self.get(tag_id, workspace_id, tenant_id)
        sent = payload.model_fields_set
        if "name" in sent:
            name = (payload.name or "").strip()
            if not name:
                raise TagValidationError("Name is required.", "name")
            existing = self._find_by_name(workspace_id, tenant_id, name)
            if existing is not None and existing.id != row.id:
                raise TagValidationError("A tag with this name already exists.", "name")
            row.name = name
        if "emoji" in sent:
            row.emoji = payload.emoji or None
        if "color" in sent:
            row.color = payload.color or None
        if "description" in sent:
            row.description = payload.description or None
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, tag_id: str, workspace_id: str, tenant_id: str) -> None:
        row = self.get(tag_id, workspace_id, tenant_id)
        self.db.query(ContactTagLink).filter(
            ContactTagLink.tag_id == row.id, ContactTagLink.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        self.db.delete(row)
        self.db.commit()

    # ── contact links (used by ContactProfileService + thread mapping) ──────
    def ids_for_contact(self, contact_id: str, tenant_id: str) -> List[str]:
        rows = (
            self.db.query(ContactTagLink.tag_id)
            .filter(ContactTagLink.contact_id == contact_id, ContactTagLink.tenant_id == tenant_id)
            .all()
        )
        return [r[0] for r in rows]

    def refs_for_contacts(self, contact_ids: List[str], tenant_id: str) -> Dict[str, List[dict]]:
        """Batched `contact_id -> [{id,name,emoji,color}]` (AC-CDM-12) - tenant-
        scoped resolution of the stored link rows."""
        if not contact_ids:
            return {}
        rows = (
            self.db.query(ContactTagLink.contact_id, ContactTag)
            .join(ContactTag, ContactTag.id == ContactTagLink.tag_id)
            .filter(
                ContactTagLink.tenant_id == tenant_id,
                ContactTagLink.contact_id.in_(contact_ids),
            )
            .order_by(func.lower(ContactTag.name).asc())
            .all()
        )
        out: Dict[str, List[dict]] = {}
        for contact_id, tag in rows:
            out.setdefault(contact_id, []).append(
                {"id": tag.id, "name": tag.name, "emoji": tag.emoji, "color": tag.color}
            )
        return out

    def validate_tag_ids(self, workspace_id: str, tenant_id: str, tag_ids: List[str]) -> List[str]:
        """Every id must belong to this workspace + tenant (the polymorphic
        stored-id rule: validated at save time) - raises on the first bad id,
        nothing is written. De-duplicates the clean set."""
        ids = list(dict.fromkeys(tag_ids or []))
        if not ids:
            return []
        rows = (
            self.db.query(ContactTag.id)
            .filter(
                ContactTag.tenant_id == tenant_id,
                ContactTag.workspace_id == workspace_id,
                ContactTag.id.in_(ids),
            )
            .all()
        )
        found = {r[0] for r in rows}
        missing = [i for i in ids if i not in found]
        if missing:
            raise TagValidationError(
                "One or more tags do not belong to this contact's workspace.", "tagIds"
            )
        return ids

    def resolve_or_create_by_name(
        self, workspace_id: str, tenant_id: str, names: List[str]
    ) -> List[str]:
        """Resolve gateway PATCH `tags: [<name>]` (AC-CDM-26, D8) to ids - an
        existing name matches case-insensitively; an unknown name is
        auto-created in the workspace (respond.io parity: internal callers
        speak ids, external ones speak names). De-duplicates (case-
        insensitive), preserving first-seen order.

        Newly-created rows are only `flush()`-ed, never committed here - the
        caller (`ContactProfileService.patch` via `ConversationService.
        patch_thread`) persists everything in ONE unit of work, so a
        downstream validation failure (e.g. bad `customFields`) rolls back the
        whole request including any tag just auto-created for it."""
        ids: List[str] = []
        seen: set = set()
        for raw in names or []:
            name = (raw or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            existing = self._find_by_name(workspace_id, tenant_id, name)
            if existing is not None:
                ids.append(existing.id)
                continue
            count = (
                self.db.query(ContactTag.id)
                .filter(ContactTag.tenant_id == tenant_id, ContactTag.workspace_id == workspace_id)
                .count()
            )
            if count >= MAX_TAGS_PER_WORKSPACE:
                raise TagValidationError(
                    f"This workspace already has {MAX_TAGS_PER_WORKSPACE} tags (the maximum).",
                    "tags",
                )
            row = ContactTag(tenant_id=tenant_id, workspace_id=workspace_id, name=name)
            self.db.add(row)
            self.db.flush()
            ids.append(row.id)
        return ids

    def replace_links(self, contact: Contact, tag_ids: List[str]) -> None:
        """REPLACE the contact's whole tag set (AC-CDM-10) - never a merge.
        Caller (`ContactProfileService`) has already validated `tag_ids`."""
        self.db.query(ContactTagLink).filter(
            ContactTagLink.contact_id == contact.id, ContactTagLink.tenant_id == contact.tenant_id
        ).delete(synchronize_session=False)
        self.db.flush()
        for tag_id in tag_ids:
            self.db.add(
                ContactTagLink(tenant_id=contact.tenant_id, contact_id=contact.id, tag_id=tag_id)
            )
        self.db.flush()
