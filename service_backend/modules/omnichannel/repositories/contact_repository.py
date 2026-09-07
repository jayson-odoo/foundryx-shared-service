"""Contact (thread) + message repository - tenant-scoped, pure SQLAlchemy.

The contact IS the thread (plan 05): list/filter threads, fetch a thread's
messages, resolve identities, and maintain the thread metadata columns the
inbox sorts/filters on.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from ..models import (
    Channel,
    Contact,
    ContactChannelIdentity,
    ContactTagLink,
    ConversationMessage,
    MessageReaction,
    Status,
)


def _unreplied_expr():
    """AC-IVE Definitions - `unreplied` = there IS an inbound message and
    either no agent reply has ever landed or the last one predates it."""
    return and_(
        Contact.last_incoming_message_at.isnot(None),
        or_(
            Contact.last_agent_message_at.is_(None),
            Contact.last_agent_message_at < Contact.last_incoming_message_at,
        ),
    )


class ContactRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── Threads ──────────────────────────────────────────────────────────────
    def list_threads(
        self,
        tenant_id: str,
        *,
        workspace_id: Optional[str] = None,
        assignee: str = "all",  # all | me | unassigned | user
        assignee_user_ids: Optional[List[str]] = None,
        me_user_id: Optional[str] = None,
        me_external_agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        team_ids: Optional[List[str]] = None,
        status_key: Optional[str] = None,  # OPEN | SNOOZED | CLOSED | None=ALL
        status_keys: Optional[List[str]] = None,  # a saved view's multi-status filter
        priority: Optional[str] = None,
        search: Optional[str] = None,
        lifecycle_stage_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
        channel_ids: Optional[List[str]] = None,
        unreplied: Optional[bool] = None,
        sort: Optional[str] = None,  # newest | oldest | unreplied_first | longest_waiting
        page: int = 0,
        page_size: int = 50,
    ) -> Tuple[List[Contact], int]:
        q = self.db.query(Contact).filter(Contact.tenant_id == tenant_id)
        if workspace_id:
            q = q.filter(Contact.workspace_id == workspace_id)
        if team_id:
            # AC-TEM-30 - orthogonal to `assignee`: combined with
            # `assignee="unassigned"` this yields exactly that team's
            # Unassigned queue. An unknown/foreign team id is never rejected
            # here (that would be an existence oracle) - it just narrows to
            # zero matching rows, same as every other id filter on this list.
            q = q.filter(Contact.assigned_team_id == team_id)
        elif team_ids:
            # AC-TEM-46 (review round 1, finding 9) - a saved view's
            # `teamIds` (plural) filter, mutually exclusive with the
            # singular explicit `team_id` above (the router merges the two,
            # explicit always wins).
            q = q.filter(Contact.assigned_team_id.in_(team_ids))
        if assignee == "me":
            # "Mine" resolves to the CALLER's identity - a federated (embed) agent
            # matches on the external-agent column, a native user on the user column.
            # B10 (round-3 codex triage): neither identity resolved is a
            # false predicate, never "no filter" (would silently return
            # every thread in the workspace instead of the caller's own).
            if me_external_agent_id:
                q = q.filter(Contact.assigned_external_agent_id == me_external_agent_id)
            elif me_user_id:
                q = q.filter(Contact.assigned_user_id == me_user_id)
            else:
                q = q.filter(sa.false())
        elif assignee == "unassigned":
            # Unassigned = neither a native user NOR a federated agent owns it.
            q = q.filter(
                Contact.assigned_user_id.is_(None),
                Contact.assigned_external_agent_id.is_(None),
            )
        elif assignee == "user":
            # B10: an empty/omitted `assignee_user_ids` must never fall
            # through to "no predicate" (every thread, regardless of
            # assignee) - the service/router 422s this case (AC-IVE-*), this
            # is the repo's own defense-in-depth false predicate.
            if assignee_user_ids:
                q = q.filter(Contact.assigned_user_id.in_(assignee_user_ids))
            else:
                q = q.filter(sa.false())
        if status_keys:
            q = q.join(Status, Contact.status_id == Status.id).filter(Status.key.in_(status_keys))
        elif status_key:
            q = q.join(Status, Contact.status_id == Status.id).filter(Status.key == status_key)
        if priority:
            q = q.filter(Contact.priority == priority)
        if lifecycle_stage_ids:
            q = q.filter(Contact.lifecycle_status_id.in_(lifecycle_stage_ids))
        if tag_ids:
            # B11 (round-3 codex triage): the correlated `contact_id ==
            # Contact.id` already pins the EXISTS to the ONE already
            # tenant-scoped outer Contact row (no cross-tenant match is
            # possible via that correlation alone), but the link row itself
            # ALSO carries `tenant_id` - filter it explicitly so this query
            # never depends solely on the correlation for its tenant safety.
            tag_match = (
                self.db.query(ContactTagLink.id)
                .filter(
                    ContactTagLink.tenant_id == tenant_id,
                    ContactTagLink.contact_id == Contact.id,
                    ContactTagLink.tag_id.in_(tag_ids),
                )
                .exists()
            )
            q = q.filter(tag_match)
        if channel_ids:
            channel_match = (
                self.db.query(ContactChannelIdentity.id)
                .filter(
                    ContactChannelIdentity.tenant_id == tenant_id,
                    ContactChannelIdentity.contact_id == Contact.id,
                    ContactChannelIdentity.channel_id.in_(channel_ids),
                )
                .exists()
            )
            q = q.filter(channel_match)
        if unreplied:
            q = q.filter(_unreplied_expr())
        if search and search.strip():
            term = f"%{search.strip()}%"
            # WhatsApp-style: name/phone OR any message body in the thread.
            message_match = (
                self.db.query(ConversationMessage.id)
                .filter(
                    ConversationMessage.contact_id == Contact.id,
                    ConversationMessage.body.ilike(term),
                )
                .exists()
            )
            full_name = (
                func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, "")
            )
            q = q.filter(
                or_(
                    full_name.ilike(term),  # covers first, last, and "First Last"
                    Contact.phone.ilike(term),
                    message_match,
                )
            )
        total = q.count()

        # Sorts (AC-IVE-16) - every ordering ends `id ASC` for stable pagination.
        if sort == "oldest":
            order_bys = [Contact.last_message_at.asc().nullslast(), Contact.id.asc()]
        elif sort == "unreplied_first":
            unreplied_rank = case((_unreplied_expr(), 0), else_=1)
            order_bys = [
                unreplied_rank.asc(),
                Contact.last_message_at.desc().nullslast(),
                Contact.id.asc(),
            ]
        elif sort == "longest_waiting":
            unreplied_rank = case((_unreplied_expr(), 0), else_=1)
            waiting_since = case(
                (_unreplied_expr(), Contact.last_incoming_message_at), else_=None
            )
            order_bys = [
                unreplied_rank.asc(),
                waiting_since.asc().nullslast(),
                Contact.last_message_at.desc().nullslast(),
                Contact.id.asc(),
            ]
        else:  # "newest" (today's default) or unspecified
            order_bys = [Contact.last_message_at.desc().nullslast(), Contact.id.asc()]

        rows = q.order_by(*order_bys).offset(page * page_size).limit(page_size).all()
        return rows, total

    def get_by_id(self, contact_id: str, tenant_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.id == contact_id)
            .first()
        )

    def testable_for_channels(
        self, tenant_id: str, channel_ids: List[str], *, now: datetime
    ) -> List[Tuple[str, Contact]]:
        """Attached channel/contact pairs usable for a free-form test reply."""
        if not channel_ids:
            return []
        return (
            self.db.query(ContactChannelIdentity.channel_id, Contact)
            .join(Contact, Contact.id == ContactChannelIdentity.contact_id)
            .filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                ContactChannelIdentity.channel_id.in_(channel_ids),
                Contact.tenant_id == tenant_id,
                Contact.csw_expires_at.isnot(None),
                Contact.csw_expires_at > now,
            )
            .order_by(
                ContactChannelIdentity.channel_id.asc(),
                Contact.first_name.asc(),
                Contact.last_name.asc(),
                Contact.id.asc(),
            )
            .all()
        )

    def is_attached_to_channel(
        self, contact_id: str, channel_id: str, tenant_id: str
    ) -> bool:
        return (
            self.db.query(ContactChannelIdentity.id)
            .filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                ContactChannelIdentity.contact_id == contact_id,
                ContactChannelIdentity.channel_id == channel_id,
            )
            .first()
            is not None
        )

    def mark_read(self, contact: Contact) -> None:
        contact.agent_last_read_at = datetime.now(timezone.utc)
        self.db.flush()

    # ── Messages ─────────────────────────────────────────────────────────────
    def list_messages(self, contact_id: str, tenant_id: str) -> List[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id == contact_id,
            )
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            .all()
        )

    def list_messages_recent(
        self,
        contact_id: str,
        tenant_id: str,
        *,
        limit: int,
        before_id: Optional[str] = None,
        after_id: Optional[str] = None,
    ) -> List[ConversationMessage]:
        """A bounded window of a contact's messages, always returned oldest→newest.

        Two-way keyset paging (respond.io next/previous):
        - ``before_id`` - the ``limit`` messages OLDER than that anchor (page back
          into history).
        - ``after_id`` - the ``limit`` messages NEWER than that anchor (page
          forward toward the present).
        - neither - the most recent ``limit`` messages.
        Never loads an entire (possibly huge) thread."""
        q = self.db.query(ConversationMessage).filter(
            ConversationMessage.tenant_id == tenant_id,
            ConversationMessage.contact_id == contact_id,
        )
        if after_id:
            anchor = self.get_message(after_id, tenant_id)
            if anchor is not None:
                q = q.filter(
                    (ConversationMessage.created_at > anchor.created_at)
                    | (
                        (ConversationMessage.created_at == anchor.created_at)
                        & (ConversationMessage.id > anchor.id)
                    )
                )
            # Ascending window from the anchor forward - already oldest→newest.
            return (
                q.order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
                .limit(limit)
                .all()
            )
        if before_id:
            anchor = self.get_message(before_id, tenant_id)
            if anchor is not None:
                q = q.filter(
                    (ConversationMessage.created_at < anchor.created_at)
                    | (
                        (ConversationMessage.created_at == anchor.created_at)
                        & (ConversationMessage.id < anchor.id)
                    )
                )
        rows = (
            q.order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))

    def get_message_global(self, message_id: str) -> Optional[ConversationMessage]:
        """Resolve a message by id WITHOUT a tenant filter. ONLY for the signed
        media path, where a verified HMAC signature is the authorization (it binds
        this exact id) - never call from a tenant-scoped request path."""
        return (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.id == message_id)
            .first()
        )

    def get_message(self, message_id: str, tenant_id: str) -> Optional[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.id == message_id,
            )
            .first()
        )

    def get_message_by_external_id(
        self, external_message_id: str, tenant_id: str
    ) -> Optional[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.external_message_id == external_message_id,
            )
            .first()
        )

    def outbound_before_watermark(
        self, contact_id: str, channel_id: str, tenant_id: str, *, at: datetime
    ) -> List[ConversationMessage]:
        """Messenger/Instagram `message_deliveries`/`message_reads` receipts
        are WATERMARK-based (plan 32 / A7a, D-A7-22), not per-message: every
        outbound row on this thread SENT AT OR BEFORE the watermark instant
        is a receipt candidate. Sender-side only (never a `CONTACT` row) -
        the caller re-checks each row's own status rank so a receipt still
        only ever moves forward (a late `SENT` watermark after `READ` is a
        no-op per row, never a regression)."""
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.channel_id == channel_id,
                ConversationMessage.sender_type != "CONTACT",
                ConversationMessage.created_at <= at,
            )
            .all()
        )

    # ── Reactions (plan 12 Slice 3) ─────────────────────────────────────────
    def set_reaction(
        self,
        target_message: ConversationMessage,
        *,
        reactor_type: str,
        reactor: str,
        emoji: Optional[str],
        workspace_id: Optional[str],
    ) -> Tuple[Optional[MessageReaction], bool]:
        """Upsert an emoji reaction (or delete on empty emoji), keyed to
        (target_message, reactor). Returns ``(row_or_None, removed)``. Caller
        commits."""
        existing = (
            self.db.query(MessageReaction)
            .filter(
                MessageReaction.target_message_id == target_message.id,
                MessageReaction.reactor == reactor,
            )
            .first()
        )
        clean = (emoji or "").strip()
        if not clean:
            if existing is not None:
                self.db.delete(existing)
                return None, True
            return None, True
        if existing is not None:
            existing.emoji = clean
            existing.reactor_type = reactor_type
            return existing, False
        row = MessageReaction(
            tenant_id=target_message.tenant_id,
            workspace_id=workspace_id,
            target_message_id=target_message.id,
            reactor_type=reactor_type,
            reactor=reactor,
            emoji=clean,
        )
        self.db.add(row)
        return row, False

    def reactions_for(self, message_ids: List[str], tenant_id: str) -> dict:
        """Batched: message_id → [{emoji, reactorType, reactor}] for the bubble
        chips."""
        if not message_ids:
            return {}
        rows = (
            self.db.query(MessageReaction)
            .filter(
                MessageReaction.tenant_id == tenant_id,
                MessageReaction.target_message_id.in_(message_ids),
            )
            .order_by(MessageReaction.created_at.asc())
            .all()
        )
        out: dict = {}
        for r in rows:
            out.setdefault(r.target_message_id, []).append(
                {"emoji": r.emoji, "reactorType": r.reactor_type, "reactor": r.reactor}
            )
        return out

    # ── Thread-list computed columns (preview + unread), batched ────────────
    def previews_for(self, contact_ids: List[str], tenant_id: str) -> dict:
        """Latest non-SYSTEM message body per contact (one grouped query)."""
        if not contact_ids:
            return {}
        latest = (
            self.db.query(
                ConversationMessage.contact_id,
                func.max(ConversationMessage.created_at).label("latest_at"),
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(contact_ids),
                ConversationMessage.sender_type != "SYSTEM",
            )
            .group_by(ConversationMessage.contact_id)
            .subquery()
        )
        rows = (
            self.db.query(ConversationMessage)
            .join(
                latest,
                (ConversationMessage.contact_id == latest.c.contact_id)
                & (ConversationMessage.created_at == latest.c.latest_at),
            )
            .all()
        )
        # Tie-break: two messages can share an identical created_at (µs-coarse
        # clocks / batched inbound). Order so the highest id wins deterministically
        # - setdefault keeps the first seen per contact.
        preview: dict = {}
        for m in sorted(rows, key=lambda r: r.id, reverse=True):
            preview.setdefault(m.contact_id, m)
        return preview

    def unread_counts_for(self, contacts: List[Contact], tenant_id: str) -> dict:
        """Inbound messages newer than each contact's agent_last_read_at."""
        if not contacts:
            return {}
        ids = [c.id for c in contacts]
        rows = (
            self.db.query(
                ConversationMessage.contact_id,
                ConversationMessage.created_at,
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(ids),
                ConversationMessage.sender_type == "CONTACT",
            )
            .all()
        )
        last_read = {c.id: c.agent_last_read_at for c in contacts}
        counts: dict = {}
        for contact_id, created_at in rows:
            marker = last_read.get(contact_id)
            if marker is not None and created_at is not None:
                # SQLite returns naive datetimes; normalise for comparison.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if marker.tzinfo is None:
                    marker = marker.replace(tzinfo=timezone.utc)
                if created_at <= marker:
                    continue
            counts[contact_id] = counts.get(contact_id, 0) + 1
        return counts

    # ── Identities (webhook contact resolution, plan 05 §4) ─────────────────
    def find_identity(
        self, channel_id: str, external_user_id: str
    ) -> Optional[ContactChannelIdentity]:
        return (
            self.db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.channel_id == channel_id,
                ContactChannelIdentity.external_user_id == external_user_id,
            )
            .first()
        )

    def find_identity_for_channel(
        self, contact_id: str, channel_id: str, tenant_id: str
    ) -> Optional[ContactChannelIdentity]:
        """The identity THIS contact has on a SPECIFIC channel (plan 32 / A7a)
        - the addressing + window-policy seam: `messaging_policy.authorize`
        reads a Messenger/Instagram identity's OWN re-engagement window off
        this row, and `channel_addressing.recipient_ref` addresses by its
        `external_user_id` (PSID/IGSID). Tenant-scoped."""
        return (
            self.db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                ContactChannelIdentity.contact_id == contact_id,
                ContactChannelIdentity.channel_id == channel_id,
            )
            .first()
        )

    def identity_windows_for(
        self, pairs: List[Tuple[str, str]], tenant_id: str
    ) -> Dict[Tuple[str, str], ContactChannelIdentity]:
        """Batched twin of `find_identity_for_channel` (plan 32 / A7a, S6) -
        ONE query for a whole page's `(contact_id, channel_id)` pairs, keyed
        back the same way, so `ThreadItem.windowExpiresAt`/
        `humanAgentExpiresAt` never cost an N+1 on the inbox list. Tenant-
        scoped like every other stored-id resolution in this repository."""
        pairs = [p for p in {p for p in pairs if p[0] and p[1]}]
        if not pairs:
            return {}
        contact_ids = {c for c, _ in pairs}
        channel_ids = {ch for _, ch in pairs}
        rows = (
            self.db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                ContactChannelIdentity.contact_id.in_(contact_ids),
                ContactChannelIdentity.channel_id.in_(channel_ids),
            )
            .all()
        )
        wanted = set(pairs)
        return {
            (r.contact_id, r.channel_id): r
            for r in rows
            if (r.contact_id, r.channel_id) in wanted
        }

    def find_by_phone_digits(
        self, phone_digits: str, workspace_id: str, tenant_id: str
    ) -> Optional[Contact]:
        """Within-workspace stitch/lookup (decision 15; indexed since plan 26
        S1, D-A2-9) - match an existing contact by its normalized
        `phone_digits` column. Empty digits (malformed `wa_id`) must NEVER
        match a digitless contact - that would mis-stitch a message onto an
        unrelated contact, so this is a plain equality on a non-empty value,
        never a wildcard.

        Falls back to a bounded scan over rows whose `phone_digits` hasn't
        been stamped yet (`IS NULL`) - a genuinely legacy row right after this
        migration lands and before a backfill runs, AND every pre-existing
        test fixture across the suite that predates this slice and inserts a
        `Contact` row directly (never through a write path that stamps
        `phone_digits`). This keeps the lookup a byte-for-byte match for the
        OLD O(n) digit-comparison scan (AC-CTM-27) regardless of backfill
        state, while the indexed exact-match above is what serves once every
        row is stamped."""
        from ..phone import digits_only

        if not phone_digits:
            return None
        exact = (
            self.db.query(Contact)
            .filter(
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
                Contact.phone_digits == phone_digits,
            )
            .first()
        )
        if exact is not None:
            return exact
        candidates = (
            self.db.query(Contact)
            .filter(
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
                Contact.phone_digits.is_(None),
                Contact.phone.isnot(None),
            )
            .all()
        )
        for c in candidates:
            if digits_only(c.phone) == phone_digits:
                return c
        return None

    def find_by_phone_in_workspace(
        self, phone_digits: str, workspace_id: str, tenant_id: str
    ) -> Optional[Contact]:
        """Back-compat alias for `find_by_phone_digits` (every existing caller
        already passes pre-digit-reduced input) - kept so `inbound_service`/
        `public_gateway_service` need no signature change."""
        return self.find_by_phone_digits(phone_digits, workspace_id, tenant_id)

    def backfill_phone_digits(self, tenant_id: Optional[str] = None) -> int:
        """Idempotent - stamps `phone_digits` on every row where it's still
        NULL but `phone` isn't (D-A2-9/AC-CTM-27). A plain Python loop (not
        raw SQL) so it runs identically on Postgres AND the SQLite test
        engine - `tests/test_omnichannel_contacts_module.py` exercises this
        FUNCTION directly (module Alembic's own `regexp_replace` backfill is
        Postgres-only and never runs under pytest - CLAUDE.md's "unit-test
        the backfill function directly" lesson). Returns the number of rows
        stamped (0 on a second call - idempotent)."""
        from ..phone import digits_only

        q = self.db.query(Contact).filter(Contact.phone_digits.is_(None), Contact.phone.isnot(None))
        if tenant_id is not None:
            q = q.filter(Contact.tenant_id == tenant_id)
        count = 0
        for c in q.all():
            digits = digits_only(c.phone)
            if digits:
                c.phone_digits = digits
                count += 1
        self.db.flush()
        return count

    # ── Channel identities decoration (plan 26 S1, AC-CTM-19/23) ────────────
    def channels_for_contacts(self, contact_ids: List[str], tenant_id: str) -> dict:
        """Batched `contact_id -> [{channelId, channelType, name}]` for a page
        of contacts - ONE query for every distinct channel identity on the
        page (never per-row), tenant-scoped on BOTH the identity and the
        joined channel row (the polymorphic stored-id rule). A contact with
        no identity is simply absent from the result (the caller defaults to
        `[]`, never a fabricated channel type - D-A2-11)."""
        if not contact_ids:
            return {}
        rows = (
            self.db.query(
                ContactChannelIdentity.contact_id,
                Channel.id,
                Channel.channel_type,
                Channel.name,
            )
            .join(Channel, Channel.id == ContactChannelIdentity.channel_id)
            .filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                Channel.tenant_id == tenant_id,
                ContactChannelIdentity.contact_id.in_(contact_ids),
            )
            .order_by(Channel.created_at.asc())
            .all()
        )
        out: dict = {}
        for contact_id, channel_id, channel_type, name in rows:
            bucket = out.setdefault(contact_id, {})
            # De-dupe per (contact, channel) - a contact can carry more than
            # one identity on the SAME channel in a pathological case.
            bucket[channel_id] = {"channelId": channel_id, "channelType": channel_type, "name": name}
        return {contact_id: list(by_channel.values()) for contact_id, by_channel in out.items()}
