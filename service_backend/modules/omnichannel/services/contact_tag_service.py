"""Contact tag registry - per-workspace tags + contact links (plan 25 S1/S2).

CRUD + case-insensitive per-workspace uniqueness + cap (500 tags, AC-CDM-09);
`replace_links` implements the `tagIds` PATCH contract (AC-CDM-10) - ids are
validated against the contact's OWN workspace before any write (polymorphic
stored-id rule: validated at save, resolved tenant + workspace scoped at
read), and the whole set is replaced, never merged. Deleting a tag removes its
links only (AC-CDM-11) - the contacts themselves are untouched.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
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

    def _find_all_by_names(
        self, workspace_id: str, tenant_id: str, names: List[str]
    ) -> Dict[str, ContactTag]:
        """Batched case-insensitive lookup - `lowered name -> ContactTag` for
        every name in `names` that already exists. ONE query for the whole
        set (the lookup pass of `resolve_or_create_by_name`), never one query
        per name."""
        if not names:
            return {}
        lowered = {n.strip().lower() for n in names if n and n.strip()}
        if not lowered:
            return {}
        rows = (
            self.db.query(ContactTag)
            .filter(
                ContactTag.tenant_id == tenant_id,
                ContactTag.workspace_id == workspace_id,
                func.lower(ContactTag.name).in_(lowered),
            )
            .all()
        )
        return {row.name.strip().lower(): row for row in rows}

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
        try:
            self.db.commit()
        except IntegrityError:
            # B9 (plan-25 round-3 codex triage): the app-level `_find_by_name`
            # check above passed, then a concurrent request's row landed
            # first - the DB backstop (`uq_contact_tags_workspace_name`,
            # Postgres functional unique index) raises here. Surface the SAME
            # 422 a same-request duplicate gets, never an unhandled 500.
            self.db.rollback()
            raise TagValidationError("A tag with this name already exists.", "name")
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
        try:
            self.db.commit()
        except IntegrityError:
            # B9: same race as `create`, for a RENAME landing on a name a
            # concurrent request just took.
            self.db.rollback()
            raise TagValidationError("A tag with this name already exists.", "name")
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
        scoped resolution of the stored link rows.

        `ContactTag.tenant_id == tenant_id` is filtered on the JOINED tag row
        too (review round 2, finding C), not just the link - a link row can
        only ever point at a same-tenant tag in practice (`replace_links`/
        `resolve_or_create_by_name` both validate/create within the caller's
        own tenant+workspace), but a planted/corrupt link (the polymorphic
        stored-id rule - never resolve a stored id unscoped) must not render
        another tenant's tag name/emoji/color to this caller."""
        if not contact_ids:
            return {}
        rows = (
            self.db.query(ContactTagLink.contact_id, ContactTag)
            .join(
                ContactTag,
                (ContactTag.id == ContactTagLink.tag_id) & (ContactTag.tenant_id == tenant_id),
            )
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
        self, workspace_id: str, tenant_id: str, names: List[str], *, _max_attempts: int = 3
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
        whole request including any tag just auto-created for it.

        Concurrency (review round 2 finding D; round 3 finding B10): two
        gateway PATCHes for the SAME unknown name can both pass the lookup
        SELECT before either INSERTs. The DB backstop
        (`uq_contact_tags_workspace_name`, Postgres functional unique index,
        review round 1 finding 9) then raises `IntegrityError` for whichever
        `flush()` loses the race.

        B10: a name list can carry SEVERAL new names in one call - the
        earlier per-name loop flushed+appended an id per name as it went, so
        a race on a LATER name's `flush()` rolled back the WHOLE session
        (SQLite has no functional unique index, so a real race can't use a
        SAVEPOINT here either - see the SAVEPOINT note below, unchanged),
        discarding the row (and id) already flushed for an EARLIER name in
        THIS SAME call while `ids` had already captured that now-nonexistent
        id. Fixed by resolving in two clean passes per attempt - a batched
        lookup (`_find_all_by_names`, ONE query) then a batched create of
        only the still-missing names - so nothing is ever appended to the
        result until the flush that produced it actually stuck. On a race,
        roll back (nothing else has been written - see below) and RESTART
        the whole resolution from the lookup pass, bounded to
        `_max_attempts` tries.

        This deliberately does NOT wrap inserts in a `begin_nested()`
        SAVEPOINT (an earlier version of this fix did, and it broke the
        sibling atomicity test - `numbering_repository.get_or_create_counter_
        for_update` uses that pattern safely because its whole call IS the
        unit of work, but here a SUCCESSFULLY released SAVEPOINT survives a
        LATER, unrelated `self.db.rollback()` on the SAME session under this
        project's SQLite test engine - i.e. it stops being undone by the
        request-level rollback a downstream 4xx triggers, silently breaking
        "the entire PATCH is rejected and nothing is written"). A losing
        `flush()` (no SAVEPOINT) instead takes the SAME recovery a `commit()`
        failure anywhere else in this codebase takes: a full `self.db.
        rollback()` of the whole batch, then retry. This only stays correct
        because tag resolution is the FIRST database write of the gateway
        PATCH (`PublicGatewayService.update_contact` calls this before
        `ConversationService.patch_thread`) - a rollback here can't discard
        other already-applied parts of the SAME request because there aren't
        any yet."""
        clean_names: List[str] = []
        seen: set = set()
        for raw in names or []:
            name = (raw or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            clean_names.append(name)
        if not clean_names:
            return []

        for attempt in range(_max_attempts):
            by_lower = self._find_all_by_names(workspace_id, tenant_id, clean_names)
            missing = [n for n in clean_names if n.lower() not in by_lower]
            if missing:
                count = (
                    self.db.query(ContactTag.id)
                    .filter(
                        ContactTag.tenant_id == tenant_id,
                        ContactTag.workspace_id == workspace_id,
                    )
                    .count()
                )
                new_rows: List[Tuple[str, ContactTag]] = []
                for name in missing:
                    if count >= MAX_TAGS_PER_WORKSPACE:
                        raise TagValidationError(
                            f"This workspace already has {MAX_TAGS_PER_WORKSPACE} tags "
                            "(the maximum).",
                            "tags",
                        )
                    row = ContactTag(tenant_id=tenant_id, workspace_id=workspace_id, name=name)
                    self.db.add(row)
                    new_rows.append((name, row))
                    count += 1
                try:
                    self.db.flush()
                except IntegrityError:
                    self.db.rollback()
                    continue  # restart the whole resolution from the lookup pass
                for name, row in new_rows:
                    by_lower[name.lower()] = row
            return [by_lower[n.lower()].id for n in clean_names]

        raise TagValidationError(
            "Could not resolve tag names due to a concurrent update - try again.", "tags"
        )

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
