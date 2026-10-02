"""``create_idea`` - the deterministic Conversational-Intake state machine (§5.1,
AC-A-17..25). NO LLM (D20): merge structured ``fields``/``remove`` into the draft
against the form_engine schema, run dedup on the problem text, recompute
captured/missing via the ``completion_rule``, then pick the status and compose a
templated ``reply_text``.

State machine (deterministic):
- no ``draft_id`` -> create a draft Idea (status ``draft``); seed ``problem`` from
  ``message_text`` when ``fields`` did not carry it.
- ``duplicate`` - a high text-similarity match (dedup seam; slice 6 wires pg_trgm).
- ``collecting`` - ``missing != []``; reply echoes captured + lists missing.
- ``review`` - ``missing == []`` AND ``confirm != true``; reply echoes the full
  summary + asks to confirm/revise; the draft STAYS ``draft`` (never auto-completes,
  AC-A-18b).
- ``complete`` - ``missing == []`` AND ``confirm == true``; the ``on_complete_sink``
  moves ``draft -> captured`` (once, idempotent) and mints the link (AC-A-20).
"""
from datetime import timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.models.catalog import Product
from app.models.status import Status
from app.services import status_machine
from modules.omnichannel.models import Contact, Workspace

from ..models import Idea, IdeaAttachment, IdeaVote
from .dedup import DedupService
from .numbering import ensure_idea_number
from .ownership import SubmitterIdentity, phone_variants
from .intake_definitions import (
    IDEATION_FIELD_LABELS,
    IDEATION_INTAKE_KEY,
    get_intake_definition,
)
from .sinks import mint_idea_link, sync_idea_columns_from_captured
from .statuses import IDEA_ENTITY, idea_status_id, initial_idea_status_id

_ONE_SHOT_FIELDS = ("proposed_solution", "impact", "department")


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
            raw_transcript=raw_transcript,
        )

        # Persist media pointers idempotently on every turn (DC-9) - before the
        # draft-status branching so attachments land on collecting/review/complete
        # alike. Sorento has already durably stored + captioned them.
        self._persist_attachments(tenant_id, idea, attachments)

        # An already-promoted draft is immutable via intake: any call returns the
        # idempotent complete result (AC-A-20 / AC-A-16 re-fire no-op).
        if not self._is_draft(idea):
            self.db.commit()
            return self._complete_output(definition, idea)

        # Stamp the submitter display name on the draft (WS-A). Latest non-blank
        # wins across turns; a blank/absent name never clobbers a set one.
        if submitter_name and submitter_name.strip():
            idea.submitter_name = submitter_name.strip()

        self._merge(idea, definition, message_text, fields, remove, raw_transcript=raw_transcript)

        captured, missing = definition.completion_rule(idea.captured_json or {})

        # Dedup on the problem text (AC-A-21/31): a high pg_trgm / difflib match to
        # an existing NON-draft Idea in the same (tenant, product) ⇒ duplicate.
        dup_id = self._dedup.find_duplicate(
            tenant_id,
            product_id,
            str((idea.captured_json or {}).get("problem") or idea.problem or ""),
            idea.id,
        )
        if dup_id is not None:
            # Upvote the existing idea once per submitter (idempotent), then relay.
            self._register_submitter_upvote(tenant_id, dup_id, submitter_contact_id)
            self.db.commit()
            return {
                "draft_id": idea.id,
                "status": "duplicate",
                "captured": captured,
                "missing": missing,
                "reply_text": _reply_duplicate(),
                "duplicate_of": dup_id,
            }

        if missing:
            self.db.commit()
            return {
                "draft_id": idea.id,
                "status": "collecting",
                "captured": captured,
                "missing": missing,
                "reply_text": _reply_collecting(captured, missing),
            }

        if not confirm:
            # NEVER auto-completes - echo the full summary and ask to confirm/revise
            # (D-CONFIRM, AC-A-18b). The draft stays ``draft``.
            self.db.commit()
            return {
                "draft_id": idea.id,
                "status": "review",
                "captured": captured,
                "missing": missing,
                "reply_text": _reply_review(captured),
            }

        # complete - explicit confirm: the sink is the ONLY promotion path.
        link = definition.on_complete_sink(self.db, idea, tenant_id)
        self.db.commit()
        return {
            "draft_id": idea.id,
            "status": "complete",
            "captured": captured,
            "missing": missing,
            "reply_text": _reply_complete(link),
            "link": link,
            "number": idea.number,
        }

    # ── one-shot create (SS-IDEATION-OWN) ─────────────────────────────────────
    def create_one_shot(
        self,
        tenant_id: str,
        *,
        product_id: str,
        problem: str,
        submitter_crm_user_id: Optional[str],
        proposed_solution: Optional[str] = None,
        impact: Optional[str] = None,
        department: Optional[str] = None,
        submitter_phone: Optional[str] = None,
        submitter_name: Optional[str] = None,
        raw_transcript: Optional[str] = None,
        attachments: Optional[List[Dict[str, object]]] = None,
        source: Optional[str] = None,
    ) -> dict:
        """Create a REAL idea in one call - the chatbot has already collected and
        confirmed the fields host-side, so there is no draft/collect/confirm loop
        here (that flow stays on ``create_idea``). The idea lands at ``captured``
        via the status engine, gets its number, and the sender is linked by CRM
        user id (required - only CRM users may submit via the chatbot) and, when
        given, by phone (find-or-create contact copy). No cross-submitter dedup:
        the host runs :meth:`similar_own` first and lets the sender decide.
        Returns ``{idea_id, number, status, link}``."""
        crm_user_id = (submitter_crm_user_id or "").strip()
        if not crm_user_id:
            raise ApiError(
                422, "submitter_required", "submitter_crm_user_id is required."
            )
        problem = (problem or "").strip()
        if not problem:
            raise ApiError(422, "problem_required", "problem is required.")
        self._product_or_404(tenant_id, product_id)
        contact_id = self._resolve_submitter_phone(tenant_id, submitter_phone)

        captured: Dict[str, object] = {"problem": problem}
        values = {
            "proposed_solution": proposed_solution,
            "impact": impact,
            "department": department,
        }
        for key in _ONE_SHOT_FIELDS:
            value = (values[key] or "").strip()
            if value:
                captured[key] = value
        transcript = (raw_transcript or "").strip()
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=initial_idea_status_id(self.db, tenant_id),
            intake_definition_key=IDEATION_INTAKE_KEY,
            problem=problem,
            raw_text=transcript or problem,
            source=(source or "").strip() or "whatsapp",
            submitter_contact_id=contact_id,
            submitter_crm_user_id=crm_user_id,
            submitter_name=(submitter_name or "").strip() or None,
            captured_json=captured,
        )
        sync_idea_columns_from_captured(idea)
        self.db.add(idea)
        self.db.flush()
        self._persist_attachments(tenant_id, idea, attachments)

        captured_id = idea_status_id(self.db, "captured", tenant_id)
        status_machine.transition(
            self.db, IDEA_ENTITY, idea, captured_id, actor=None,
            tenant_id=tenant_id, commit=False,
        )
        ensure_idea_number(self.db, idea)
        link = mint_idea_link(self.db, idea)
        self.db.commit()
        return {
            "idea_id": idea.id,
            "number": idea.number,
            "status": "captured",
            "link": link,
        }

    def similar_own(
        self,
        tenant_id: str,
        *,
        product_id: str,
        text_: str,
        submitter_crm_user_id: Optional[str] = None,
        submitter_phone: Optional[str] = None,
    ) -> dict:
        """The sender's OWN live ideas similar to ``text_`` (top 3). Identity =
        CRM user id and/or phone - at least one must be real (422 otherwise, so
        a missing identity can never fall back to name or to "everyone")."""
        ident = SubmitterIdentity(
            crm_user_id=submitter_crm_user_id, phone=submitter_phone
        )
        if ident.is_empty:
            raise ApiError(
                422,
                "submitter_required",
                "submitter_crm_user_id or a valid submitter_phone is required.",
            )
        self._product_or_404(tenant_id, product_id)
        hits = self._dedup.find_similar_own(tenant_id, product_id, text_, ident)
        if not hits:
            return {"matches": []}
        ideas = {
            i.id: i
            for i in self.db.query(Idea)
            .filter(Idea.tenant_id == tenant_id, Idea.id.in_([h[0] for h in hits]))
            .all()
        }
        status_keys = {
            s.id: s.key
            for s in self.db.query(Status)
            .filter(Status.id.in_({i.status_id for i in ideas.values()}))
            .all()
        }
        matches = []
        for idea_id, score in hits:
            idea = ideas.get(idea_id)
            if idea is None:  # pragma: no cover - same-tenant by construction
                continue
            matches.append(
                {
                    "idea_id": idea.id,
                    "number": idea.number,
                    "problem": idea.problem,
                    "status": status_keys.get(idea.status_id, ""),
                    "similarity": round(score, 3),
                    "created_at": _iso_z(idea.created_at),
                    "link": mint_idea_link(self.db, idea),
                }
            )
        return {"matches": matches}

    def _product_or_404(self, tenant_id: str, product_id: str) -> Product:
        product = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )
        if product is None:
            raise ApiError(404, "unknown_product", "product_id does not resolve to a product for this workspace.")
        return product

    def _resolve_submitter_phone(
        self, tenant_id: str, phone: Optional[str]
    ) -> Optional[str]:
        """Phone → this tenant's contact copy (matched across ``+``/digit-only
        spellings; created as ``+<digits>`` when absent). ``None`` when no phone
        was supplied; 422 when one was supplied but is not a real number."""
        if phone is None or not phone.strip():
            return None
        variants = phone_variants(phone)
        if not variants:
            raise ApiError(422, "invalid_phone", "submitter_phone is not a valid phone number.")
        existing = (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.phone.in_(variants))
            .order_by(Contact.id.asc())
            .first()
        )
        if existing is not None:
            return existing.id
        return self._resolve_submitter(tenant_id, variants[0])

    # ── internals ─────────────────────────────────────────────────────────────
    def _is_draft(self, idea: Idea) -> bool:
        return idea.status_id == initial_idea_status_id(self.db, idea.tenant_id)

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
        exists = (
            self.db.query(IdeaVote)
            .filter(
                IdeaVote.idea_id == idea_id,
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
        rows = self.db.query(IdeaVote).filter(IdeaVote.idea_id == idea_id).all()
        existing = self.db.query(Idea).filter(Idea.id == idea_id).first()
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
    ) -> Idea:
        if draft_id:
            idea = (
                self.db.query(Idea)
                .filter(Idea.id == draft_id, Idea.tenant_id == tenant_id)
                .first()
            )
            if idea is None:
                raise ApiError(404, "unknown_draft", "draft_id does not resolve to an open draft.")
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

    def _complete_output(self, definition, idea: Idea) -> dict:
        captured, missing = definition.completion_rule(idea.captured_json or {})
        link = mint_idea_link(self.db, idea)
        return {
            "draft_id": idea.id,
            "status": "complete",
            "captured": captured,
            "missing": missing,
            "reply_text": _reply_complete(link),
            "link": link,
            "number": idea.number,
        }


def _iso_z(dt) -> Optional[str]:
    """Aware-UTC datetime → ISO-8601 with a ``Z`` suffix (wire convention)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── deterministic reply_text templates (no LLM, D20) ──────────────────────────


def _label(key: str) -> str:
    return IDEATION_FIELD_LABELS.get(key, key)


def _captured_lines(captured: Dict[str, object]) -> str:
    return "\n".join(f"- {_label(k)}: {v}" for k, v in captured.items())


def _reply_collecting(captured: Dict[str, object], missing: List[str]) -> str:
    lines = _captured_lines(captured)
    still = ", ".join(_label(k) for k in missing)
    prefix = "Here's what I've got so far:\n" + lines + "\n\n" if captured else ""
    return f"{prefix}Still need: {still}."


def _reply_review(captured: Dict[str, object]) -> str:
    return (
        "Here's your idea:\n"
        + _captured_lines(captured)
        + "\n\nReply 'confirm' to submit it, or tell me what to change."
    )


def _reply_complete(link: Optional[str]) -> str:
    if link:
        return f"Your idea has been captured. Track it here: {link}"
    return "Your idea has been captured."


def _reply_duplicate() -> str:
    return "This is similar to an existing idea - I've upvoted it for you."
