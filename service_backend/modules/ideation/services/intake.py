"""``create_idea`` - the deterministic Conversational-Intake state machine (§5.1,
S1 intake-contract redesign). NO LLM (D20): merge structured ``fields``/``remove``
into the draft against the form_engine schema, apply ``skip``/``cancel``/
``duplicate_choice``, run dedup on the problem text, recompute captured/missing +
``next_field`` via the ``completion_rule``/``next_field`` helper, then pick the
status and compose a templated ``reply_text``.

Response envelope (S1, AC-1116): every turn returns the FULL ten-key envelope -
``status, draft_id, reply_text, missing, next_field, title, captured,
duplicate_candidate, idea_number, link`` - null/empty where not applicable, never
an omitted key.

Turn algorithm (deterministic):
1. Resolve product/submitter, load-or-create the draft, persist attachments.
   While the idea is still a draft: validate + stamp ``title`` (1-8 words, 422
   ``title_too_long`` otherwise) and ``submitter_tier`` (latest non-blank wins).
2. An already-promoted draft is immutable via intake: idempotent terminal echo -
   ``rejected`` -> ``cancelled``, ``duplicate`` -> ``voted``, anything else (already
   captured+) -> ``complete``.
3. ``cancel: true`` -> ``draft -> rejected``, status ``cancelled`` (no idea_number,
   no link).
4. Merge ``fields``/``remove``, apply ``skip`` (recorded in ``intake_state``,
   answering a key later un-skips it).
5. ``duplicate_choice`` (only actioned when a candidate is pending): ``vote``
   upvotes the candidate, closes the draft (``draft -> duplicate``), status
   ``voted``; ``separate`` moves the candidate into ``declined_candidates`` and
   continues the turn.
6. Dedup on the problem text, excluding the draft itself + every declined
   candidate; a match sets ``pending_candidate`` and returns
   ``duplicate_candidate`` (no upvote, draft stays open).
7. ``missing``/``next_field`` (``OPTIONAL_ASK_ORDER``, ``department`` never asked).
8. ``missing`` non-empty or ``next_field`` set -> ``collecting``; else
   ``confirm != true`` -> ``review``; else the sink promotes to ``captured`` and
   mints ``idea_number``/``status_token`` -> ``complete``.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.models.catalog import Product
from app.models.status import Status
from app.services import status_machine
from app.services.status_machine import StatusMachineError
from modules.omnichannel.models import Contact, Workspace

from ..models import Idea, IdeaAttachment, IdeaVote
from .dedup import DedupService, dead_candidate_status_ids
from .intake_definitions import (
    IDEATION_INTAKE_KEY,
    IDEATION_RECAP_LABELS,
    OPTIONAL_ASK_ORDER,
    get_intake_definition,
    next_field as compute_next_field,
)
from .sinks import mint_idea_link, sync_idea_columns_from_captured
from .statuses import IDEA_ENTITY, idea_status_id, initial_idea_status_id

_RECAP_ORDER = ("problem", "proposed_solution", "impact", "department")


def _response(
    *,
    status: str,
    draft_id: str,
    reply_text: str,
    missing: Optional[List[str]] = None,
    next_field: Optional[str] = None,
    title: Optional[str] = None,
    captured: Optional[Dict[str, object]] = None,
    duplicate_candidate: Optional[Dict[str, object]] = None,
    idea_number: Optional[str] = None,
    link: Optional[str] = None,
) -> dict:
    return {
        "status": status,
        "draft_id": draft_id,
        "reply_text": reply_text,
        "missing": missing or [],
        "next_field": next_field,
        "title": title,
        "captured": captured or {},
        "duplicate_candidate": duplicate_candidate,
        "idea_number": idea_number,
        "link": link,
    }


class _IntakeState:
    """The turn-algorithm bookkeeping stored in ``Idea.intake_state`` (S1) -
    never holds answers (those stay in ``captured_json``)."""

    def __init__(
        self,
        skipped: Optional[set] = None,
        declined_candidates: Optional[List[str]] = None,
        pending_candidate: Optional[str] = None,
        voted_for: Optional[str] = None,
    ):
        self.skipped = set(skipped or [])
        self.declined_candidates = list(declined_candidates or [])
        self.pending_candidate = pending_candidate
        self.voted_for = voted_for

    @classmethod
    def load(cls, idea: Idea) -> "_IntakeState":
        state = idea.intake_state or {}
        return cls(
            skipped=set(state.get("skipped") or []),
            declined_candidates=list(state.get("declined_candidates") or []),
            pending_candidate=state.get("pending_candidate"),
            voted_for=state.get("voted_for"),
        )

    def save(self, idea: Idea) -> None:
        idea.intake_state = {
            "skipped": sorted(self.skipped),
            "declined_candidates": list(self.declined_candidates),
            "pending_candidate": self.pending_candidate,
            "voted_for": self.voted_for,
        }


class IntakeService:
    """The single home of intake logic (D7) - sorento/n8n never re-implement it."""

    def __init__(self, db: Session):
        self.db = db
        self._dedup = DedupService(db)

    # ── public entrypoint ─────────────────────────────────────────────────────
    def create_idea(
        self,
        tenant_id: str,
        *,
        product_id: str,
        submitter_contact_id: Optional[str],
        submitter_name: Optional[str] = None,
        message_text: str,
        raw_transcript: Optional[str] = None,
        attachments: Optional[List[Dict[str, object]]] = None,
        draft_id: Optional[str] = None,
        discard_draft_id: Optional[str] = None,
        fields: Optional[Dict[str, object]] = None,
        remove: Optional[List[str]] = None,
        confirm: bool = False,
        is_test: bool = False,
        title: Optional[str] = None,
        skip: Optional[List[str]] = None,
        cancel: Optional[bool] = None,
        duplicate_choice: Optional[str] = None,
        submitter_tier: Optional[str] = None,
    ) -> dict:
        definition = get_intake_definition(IDEATION_INTAKE_KEY)
        if definition is None:  # pragma: no cover - registered at boot
            raise ApiError(500, "intake_unavailable", "Intake definition not registered.")

        # is_new_idea restart (DC-10): the host opened a fresh draft (no draft_id)
        # and named the abandoned one - reject it so it does not linger as a phantom.
        # Best-effort: an unknown / already-terminal draft is a no-op, never a 500.
        if discard_draft_id:
            self._discard_draft(tenant_id, discard_draft_id)

        # product_id is validated against the tenant's catalog (binding-derivation
        # spoof-refusal is the respond.io slice; here we reject unknown/foreign).
        product = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )
        if product is None:
            raise ApiError(404, "unknown_product", "product_id does not resolve to a product for this workspace.")

        # Resolve the submitter to a shared-service contact id. Per §5.1/D21 the
        # caller passes a PHONE (E.164); shared-service matches it to its own
        # contact copy (find-or-create by phone). An existing Contact id is also
        # accepted as-is. (Full respond.io cron sync is a later slice; this is the
        # minimal match so a real turn never FK-violates on submitter_contact_id.)
        submitter_contact_id = self._resolve_submitter(tenant_id, submitter_contact_id)

        idea = self._load_or_create_draft(
            tenant_id, product_id, submitter_contact_id, message_text, draft_id,
            raw_transcript=raw_transcript, is_test=is_test,
        )

        # Persist media pointers idempotently on every turn (DC-9) - before the
        # draft-status branching so attachments land on collecting/review/complete
        # alike. Sorento has already durably stored + captioned them.
        self._persist_attachments(tenant_id, idea, attachments)

        # An already-promoted draft is immutable via intake: any call returns the
        # idempotent terminal echo (AC-1109 vote-idempotent / AC-1113 cancel-
        # idempotent / AC-A-20 complete re-fire no-op).
        if not self._is_draft(idea):
            return self._terminal_echo(definition, idea)

        # Stamp title/submitter_tier on every turn while draft (S1, AC-1105/1115).
        # A blank/whitespace title is treated as absent; latest non-blank value
        # across turns wins for both. The 8-word check never fires on a
        # ``cancel:true`` turn (review round 1, nit 11) - abandoning a draft
        # must never 422 on a title the submitter is about to throw away.
        if title is not None and title.strip():
            stripped_title = title.strip()
            if not cancel and len(stripped_title.split()) > 8:
                raise ApiError(422, "title_too_long", "Title must be 8 words or fewer.")
            idea.title = stripped_title
        if submitter_tier is not None and submitter_tier.strip():
            idea.submitter_tier = submitter_tier.strip()

        # Stamp the submitter display name on the draft (WS-A). Latest non-blank
        # wins across turns; a blank/absent name never clobbers a set one.
        if submitter_name and submitter_name.strip():
            idea.submitter_name = submitter_name.strip()

        if cancel:
            return self._cancel_draft(idea, tenant_id)

        self._merge(idea, definition, message_text, fields, remove, raw_transcript=raw_transcript)

        state = _IntakeState.load(idea)
        captured, missing = definition.completion_rule(idea.captured_json or {})

        for key in skip or []:
            if key in OPTIONAL_ASK_ORDER:
                state.skipped.add(key)
        # Answering a key later un-skips it (answer wins).
        state.skipped -= set(captured.keys())

        if duplicate_choice and state.pending_candidate:
            if duplicate_choice == "vote":
                # Resolve tenant+product scoped AND require the candidate is
                # still LIVE (review round 1, blocking #3) - a polymorphic
                # stored id (`pending_candidate`) is never trusted unscoped.
                # Gone/no-longer-live -> drop it and fall through to a normal
                # turn instead of voting for a dead row.
                candidate = self._resolve_live_candidate(idea, state.pending_candidate)
                if candidate is not None:
                    return self._vote_duplicate(idea, tenant_id, state, candidate, submitter_contact_id)
                state.pending_candidate = None
            elif duplicate_choice == "separate":
                state.declined_candidates.append(state.pending_candidate)
                state.pending_candidate = None
            # Any other value (schema already restricts to vote|separate) is
            # ignored - fall through to the normal turn.

        # Dedup on the problem text (AC-1107/1110): a high pg_trgm / difflib match
        # to an existing NON-draft Idea in the same (tenant, product), excluding
        # this draft itself and every candidate already declined this session.
        # ``idea.product_id`` (the DRAFT's own product), never the request's
        # ``product_id`` - a continuation turn's body must never re-scope dedup
        # to a different product than the draft actually belongs to (review
        # round 1, should-fix #7).
        problem_text = str((idea.captured_json or {}).get("problem") or idea.problem or "")
        dup_id = self._dedup.find_duplicate(
            tenant_id,
            idea.product_id,
            problem_text,
            [idea.id, *state.declined_candidates],
            is_test=idea.is_test,
        )
        state.pending_candidate = dup_id
        state.save(idea)

        if dup_id is not None:
            self.db.commit()
            return self._duplicate_candidate_response(idea, dup_id, captured, missing, idea.title)

        next_key = compute_next_field(captured, state.skipped)
        self.db.flush()

        if missing or next_key is not None:
            self.db.commit()
            return _response(
                status="collecting",
                draft_id=idea.id,
                reply_text=_reply_collecting(idea.title, captured, missing, next_key),
                missing=missing,
                next_field=next_key,
                title=idea.title,
                captured=captured,
            )

        if not confirm:
            # NEVER auto-completes - echo the full summary and ask to confirm/revise
            # (D-CONFIRM, AC-A-18b). The draft stays ``draft``.
            self.db.commit()
            return _response(
                status="review",
                draft_id=idea.id,
                reply_text=_reply_review(idea.title, captured),
                missing=missing,
                title=idea.title,
                captured=captured,
            )

        # complete - explicit confirm: the sink is the ONLY promotion path.
        link = definition.on_complete_sink(self.db, idea, tenant_id)
        self.db.commit()
        return _response(
            status="complete",
            draft_id=idea.id,
            reply_text=_reply_complete(idea.title, idea.idea_number, link),
            missing=missing,
            title=idea.title,
            captured=captured,
            idea_number=idea.idea_number,
            link=link,
        )

    # ── internals ─────────────────────────────────────────────────────────────
    def _is_draft(self, idea: Idea) -> bool:
        return idea.status_id == initial_idea_status_id(self.db, idea.tenant_id)

    def _status_key(self, idea: Idea) -> str:
        row = self.db.query(Status).filter(Status.id == idea.status_id).first()
        return row.key if row else ""

    def _resolve_candidate(self, idea: Idea, candidate_id: Optional[str]) -> Optional[Idea]:
        """Tenant + product scoped lookup of a stored candidate id
        (``pending_candidate``/``voted_for`` in ``intake_state``) - a
        polymorphic stored id is NEVER resolved unscoped (CLAUDE.md's
        recurring cross-tenant leak class; review round 1, blocking #3). No
        liveness requirement - for DISPLAY of an id already locked in by a
        past vote (``_terminal_echo``), not for deciding whether to vote."""
        if not candidate_id:
            return None
        return (
            self.db.query(Idea)
            .filter(
                Idea.id == candidate_id,
                Idea.tenant_id == idea.tenant_id,
                Idea.product_id == idea.product_id,
            )
            .first()
        )

    def _resolve_live_candidate(self, idea: Idea, candidate_id: Optional[str]) -> Optional[Idea]:
        """Same tenant+product scoping as ``_resolve_candidate``, but also
        requires the candidate is still LIVE (not draft/rejected/duplicate/
        archived - the shared dedup candidacy predicate) - for deciding
        whether a ``duplicate_choice: "vote"`` may actually fire. A candidate
        that vanished or got archived between the offer and the vote must
        never be voted for (review round 1, blocking #3)."""
        candidate = self._resolve_candidate(idea, candidate_id)
        if candidate is None:
            return None
        if candidate.status_id in dead_candidate_status_ids(self.db, idea.tenant_id):
            return None
        return candidate

    def _discard_draft(self, tenant_id: str, discard_draft_id: str) -> None:
        """Reject an abandoned draft on an is_new_idea restart (DC-10). Best-effort:
        an unknown, cross-tenant, or already-non-draft id is a silent no-op - the
        new idea proceeds regardless (never a 500 that breaks the turn)."""
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == discard_draft_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None or not self._is_draft(idea):
            return
        rejected_id = idea_status_id(self.db, "rejected", tenant_id)
        if rejected_id is None:  # pragma: no cover - seeded at boot
            return
        try:
            status_machine.transition(
                self.db, IDEA_ENTITY, idea, rejected_id,
                tenant_id=tenant_id, commit=False,
            )
        except Exception:  # noqa: BLE001 - a blocked edge must not fail the turn
            return

    def _persist_attachments(
        self, tenant_id: str, idea: Idea, attachments: Optional[List[Dict[str, object]]]
    ) -> None:
        """Upsert media pointers on the idea, keyed by ``(idea_id, source_msg_id)``
        so the same media re-sent across turns updates one row, never duplicates
        (DC-9 idempotency). ``type`` maps to the model's ``kind``. Mutable metadata
        (url / filename / caption) is refreshed on re-send (e.g. a better vision
        caption on a retried turn). Rows without a ``source_msg_id`` or ``url`` are
        skipped defensively."""
        if not attachments:
            return
        existing = {
            a.source_msg_id: a
            for a in self.db.query(IdeaAttachment)
            .filter(IdeaAttachment.idea_id == idea.id)
            .all()
        }
        for att in attachments:
            source_msg_id = str(att.get("source_msg_id") or "").strip()
            url = str(att.get("url") or "").strip()
            if not source_msg_id or not url:
                continue
            kind = str(att.get("type") or "").strip() or "file"
            filename = att.get("filename") or None
            caption = att.get("caption") or None
            row = existing.get(source_msg_id)
            if row is None:
                self.db.add(
                    IdeaAttachment(
                        tenant_id=tenant_id,
                        idea_id=idea.id,
                        source_msg_id=source_msg_id,
                        kind=kind,
                        url=url,
                        filename=filename,
                        caption=caption,
                    )
                )
            else:
                row.kind = kind
                row.url = url
                row.filename = filename
                row.caption = caption
        self.db.flush()

    def _register_submitter_upvote(
        self, tenant_id: str, idea_id: str, submitter_contact_id: Optional[str]
    ) -> None:
        """Add the duplicate submitter's upvote to the existing Idea (AC-A-21).

        One vote row per ``(idea, voter)`` (UNIQUE) makes it idempotent - a repeat
        duplicate from the same submitter does not double-count; distinct
        submitters each add a vote. Tallies are recomputed from ``idea_votes`` (the
        source of truth). No submitter id ⇒ nothing to attribute a vote to."""
        if not submitter_contact_id:
            return
        # Tenant-scoped throughout (review round 1, blocking #3) - the vote
        # insert, the tally query, and the idea row it recomputes onto all
        # filter on ``tenant_id`` too, never id-alone.
        exists = (
            self.db.query(IdeaVote)
            .filter(
                IdeaVote.idea_id == idea_id,
                IdeaVote.tenant_id == tenant_id,
                IdeaVote.voter_id == submitter_contact_id,
            )
            .first()
        )
        if exists is None:
            self.db.add(
                IdeaVote(
                    tenant_id=tenant_id,
                    idea_id=idea_id,
                    voter_id=submitter_contact_id,
                    dir="up",
                )
            )
            self.db.flush()
        rows = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.idea_id == idea_id, IdeaVote.tenant_id == tenant_id)
            .all()
        )
        existing = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if existing is not None:
            existing.upvotes = sum(1 for r in rows if r.dir == "up")
            existing.downvotes = sum(1 for r in rows if r.dir == "down")
            self.db.flush()

    def _resolve_submitter(
        self, tenant_id: str, submitter_contact_id: Optional[str]
    ) -> Optional[str]:
        """Map the caller's submitter (a phone E.164 per §5.1/D21, or an existing
        Contact id) to a shared-service Contact id - find-or-create by phone so a
        real turn never FK-violates. Returns None when no submitter was supplied."""
        if not submitter_contact_id:
            return None
        # Already a real contact id for this tenant? Use it as-is.
        existing = (
            self.db.query(Contact)
            .filter(Contact.id == submitter_contact_id, Contact.tenant_id == tenant_id)
            .first()
        )
        if existing is not None:
            return existing.id
        # Otherwise treat it as a phone (E.164) - match our own copy, else create.
        phone = submitter_contact_id.strip()
        by_phone = (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.phone == phone)
            .first()
        )
        if by_phone is not None:
            return by_phone.id
        # New contact copy needs a workspace (Contact.workspace_id is NOT NULL).
        # Use the tenant's workspace (the respond.io binding picks the exact one in
        # the later slice; here the tenant's workspace is sufficient).
        workspace = (
            self.db.query(Workspace).filter(Workspace.tenant_id == tenant_id).first()
        )
        if workspace is None:
            raise ApiError(
                422,
                "no_workspace",
                "No workspace for this tenant to attach the submitter contact to.",
            )
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace.id,
            phone=phone,
            first_name=phone,
        )
        self.db.add(contact)
        self.db.flush()
        return contact.id

    def _load_or_create_draft(
        self,
        tenant_id: str,
        product_id: str,
        submitter_contact_id: Optional[str],
        message_text: str,
        draft_id: Optional[str],
        raw_transcript: Optional[str] = None,
        is_test: bool = False,
    ) -> Idea:
        if draft_id:
            idea = (
                self.db.query(Idea)
                .filter(Idea.id == draft_id, Idea.tenant_id == tenant_id)
                .first()
            )
            if idea is None:
                raise ApiError(404, "unknown_draft", "draft_id does not resolve to an open draft.")
            # ``is_test`` is stamped once on creation and kept for the life of the
            # draft (issue #1179) - a continuation turn never flips it either way,
            # so a real idea can never quietly become a test one or vice versa.
            return idea

        # Turn 1 - a brand-new draft Idea (AC-A-19). Seed ``problem`` from the raw
        # message so the draft is valid + dedup has text; ``fields`` still win.
        # ``raw_text`` prefers the cumulative transcript (WS-B) when the host sends
        # it, else the single message; ``problem`` always seeds from the message.
        raw = (message_text or "").strip()
        transcript = (raw_transcript or "").strip()
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=initial_idea_status_id(self.db, tenant_id),
            intake_definition_key=IDEATION_INTAKE_KEY,
            problem=raw,
            raw_text=transcript or raw,
            source="whatsapp",
            submitter_contact_id=submitter_contact_id,
            captured_json={"problem": raw} if raw else {},
            is_test=is_test,
        )
        self.db.add(idea)
        self.db.flush()
        return idea

    def _merge(
        self,
        idea: Idea,
        definition,
        message_text: Optional[str],
        fields: Optional[Dict[str, object]],
        remove: Optional[List[str]],
        raw_transcript: Optional[str] = None,
    ) -> None:
        """Merge ``fields`` (add/change) and ``remove`` (clear) into the draft's
        ``captured_json`` against the schema. ``fields`` win over the message seed;
        ``remove`` is applied last so it is authoritative (drops to collecting)."""
        captured_json: Dict[str, object] = dict(idea.captured_json or {})
        schema_keys = {f.key for f in definition.target_schema.input_fields() if f.key}

        # raw_text = the CUMULATIVE transcript when the host sends it (WS-B - the
        # whole convo, not just the finalizing turn). Legacy fallback: when no
        # transcript is supplied, refresh with the latest message (old D9 behaviour).
        transcript = (raw_transcript or "").strip()
        raw = (message_text or "").strip()
        if transcript:
            idea.raw_text = transcript
        elif raw:
            idea.raw_text = raw

        for key, value in (fields or {}).items():
            if key in schema_keys:
                captured_json[key] = value
        for key in remove or []:
            captured_json.pop(key, None)

        idea.captured_json = captured_json
        # Keep the first-class segregated columns (problem / proposed_solution /
        # impact / department) in sync with the captured answers - read surface +
        # dedup rely on ``problem``, the operator UI on the rest.
        sync_idea_columns_from_captured(idea)
        # Force SQLAlchemy to detect the JSON mutation (reassigned above - safe).
        self.db.flush()

    def _cancel_draft(self, idea: Idea, tenant_id: str) -> dict:
        rejected_id = idea_status_id(self.db, "rejected", tenant_id)
        if rejected_id is None:
            # No ``rejected`` status on this tier - a cancel can never be
            # applied. Never answer ``cancelled`` for a mutation that did not
            # happen (review round 1, should-fix #4).
            self.db.rollback()
            raise ApiError(409, "transition_blocked", "This idea cannot be cancelled right now.")
        try:
            status_machine.transition(
                self.db, IDEA_ENTITY, idea, rejected_id, actor=None, tenant_id=tenant_id, commit=False
            )
        except StatusMachineError:
            # A forked tenant status set missing the draft -> rejected edge
            # (or any other engine refusal) is a 409, never a 500 (review
            # round 1, should-fix #4).
            self.db.rollback()
            raise ApiError(409, "transition_blocked", "This idea cannot be cancelled right now.")
        self.db.commit()
        return _response(
            status="cancelled", draft_id=idea.id, reply_text=_reply_cancelled(), title=idea.title
        )

    def _vote_duplicate(
        self,
        idea: Idea,
        tenant_id: str,
        state: _IntakeState,
        candidate: Idea,
        submitter_contact_id: Optional[str],
    ) -> dict:
        """Vote for an ALREADY tenant+product-scoped, live ``candidate``
        (resolved by the caller via ``_resolve_live_candidate`` - review round
        1, blocking #3)."""
        self._register_submitter_upvote(tenant_id, candidate.id, submitter_contact_id)
        state.voted_for = candidate.id
        state.pending_candidate = None
        state.save(idea)
        duplicate_id = idea_status_id(self.db, "duplicate", tenant_id)
        if duplicate_id is None:
            self.db.rollback()
            raise ApiError(409, "transition_blocked", "This idea cannot be voted right now.")
        try:
            status_machine.transition(
                self.db, IDEA_ENTITY, idea, duplicate_id, actor=None, tenant_id=tenant_id, commit=False
            )
        except StatusMachineError:
            # A forked tenant status set missing the draft -> duplicate edge
            # is a 409, never a 500 (review round 1, should-fix #4).
            self.db.rollback()
            raise ApiError(409, "transition_blocked", "This idea cannot be voted right now.")
        # Compute the candidate link BEFORE commit (review round 1, should-fix
        # #6) - a pure read now (mint_idea_link never mutates), but this keeps
        # the ordering honest regardless.
        cand_number = candidate.idea_number
        cand_link = mint_idea_link(self.db, candidate)
        self.db.commit()
        return _response(
            status="voted",
            draft_id=idea.id,
            reply_text=_reply_voted(cand_number, cand_link),
            title=idea.title,
            idea_number=cand_number,
            link=cand_link,
        )

    def _duplicate_candidate_response(
        self,
        idea: Idea,
        dup_id: str,
        captured: Dict[str, object],
        missing: List[str],
        title: Optional[str],
    ) -> dict:
        candidate = self._resolve_candidate(idea, dup_id)
        cand_title = None
        cand_number = None
        if candidate is not None:
            cand_title = (candidate.title or "").strip() or candidate.problem
            cand_number = candidate.idea_number
        return _response(
            status="duplicate_candidate",
            draft_id=idea.id,
            reply_text=_reply_duplicate_candidate(cand_title or ""),
            missing=missing,
            title=title,
            captured=captured,
            duplicate_candidate={"idea_number": cand_number, "title": cand_title},
        )

    def _terminal_echo(self, definition, idea: Idea) -> dict:
        """Idempotent terminal echo (AC-1109/1113/A-20): the draft has already
        been closed by a prior turn - re-derive the same response, never a new
        mutation."""
        status_key = self._status_key(idea)
        if status_key == "rejected":
            self.db.commit()
            return _response(
                status="cancelled", draft_id=idea.id, reply_text=_reply_cancelled(), title=idea.title
            )
        if status_key == "duplicate":
            state = _IntakeState.load(idea)
            candidate = self._resolve_candidate(idea, state.voted_for)
            cand_number = candidate.idea_number if candidate else None
            cand_link = mint_idea_link(self.db, candidate) if candidate else None
            self.db.commit()
            return _response(
                status="voted",
                draft_id=idea.id,
                reply_text=_reply_voted(cand_number, cand_link),
                title=idea.title,
                idea_number=cand_number,
                link=cand_link,
            )
        # captured (or further along the lifecycle) - the completion echo.
        captured, missing = definition.completion_rule(idea.captured_json or {})
        link = mint_idea_link(self.db, idea)
        self.db.commit()
        return _response(
            status="complete",
            draft_id=idea.id,
            reply_text=_reply_complete(idea.title, idea.idea_number, link),
            missing=missing,
            title=idea.title,
            captured=captured,
            idea_number=idea.idea_number,
            link=link,
        )


# ── deterministic reply_text templates (no LLM, D20; S1 point-form R10/R16) ────


def _title_line(title: Optional[str]) -> Optional[str]:
    t = (title or "").strip()
    return f'"{t}"' if t else None


def _recap_lines(captured: Dict[str, object]) -> List[str]:
    lines = []
    for key in _RECAP_ORDER:
        if key in captured:
            lines.append(f"{IDEATION_RECAP_LABELS[key]}: {captured[key]}")
    return lines


def _compose(title: Optional[str], recap_lines: List[str], last_line: str) -> str:
    lines: List[str] = []
    t = _title_line(title)
    if t:
        lines.append(t)
    lines.extend(recap_lines)
    lines.append(last_line)
    return "\n".join(lines)


def _reply_collecting(
    title: Optional[str],
    captured: Dict[str, object],
    missing: List[str],
    next_key: Optional[str],
) -> str:
    if missing:
        last = "What's the idea or problem you'd like to raise?"
    elif next_key == "proposed_solution":
        last = "What's your proposed solution?"
    elif next_key == "impact":
        last = "What's the impact if we do this?"
    else:  # pragma: no cover - collecting is only reached via one of the above
        last = "What's the idea or problem you'd like to raise?"
    return _compose(title, _recap_lines(captured), last)


def _reply_review(title: Optional[str], captured: Dict[str, object]) -> str:
    return _compose(title, _recap_lines(captured), "Submit it?")


def _reply_duplicate_candidate(candidate_title: str) -> str:
    return "\n".join(
        [
            f"Similar idea exists: {candidate_title}",
            "Vote for that one, or keep yours separate?",
        ]
    )


def _reply_complete(title: Optional[str], idea_number: Optional[str], link: Optional[str]) -> str:
    lines: List[str] = []
    t = _title_line(title)
    if t:
        lines.append(t)
    lines.append(f"Idea {idea_number} is in. We'll update you on WhatsApp.")
    if link:
        lines.append(f"Track it here: {link}")
    return "\n".join(lines)


def _reply_voted(idea_number: Optional[str], link: Optional[str]) -> str:
    lines = [f"Thanks, your vote is on {idea_number}."]
    if link:
        lines.append(f"Track it here: {link}")
    return "\n".join(lines)


def _reply_cancelled() -> str:
    return "No worries, I've dropped that idea. Say the word anytime you want to start again."
