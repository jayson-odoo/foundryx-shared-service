"""Business Requirement service (Phase B-i slice 2, AC-BI-15..19).

The ideation module has no ``repositories/`` layer — its services query the ORM
directly (module convention). Reads are tenant-scoped; the router stays HTTP-only.

Load-bearing rules enforced here:
- **Stamp at create (AC-BI-16):** a BR copies ``template_key`` + the active
  template version int, and ``answers_json`` is validated against the STAMPED
  version's ``doc_json`` — read by ``(template_key, template_version)`` — never
  the current active one.
- **Idea↔BR link (AC-BI-17):** tenant-scoped + same-product; a cross-tenant or
  cross-product idea id is refused on write (the polymorphic-target rule), and
  resolution on read is tenant-scoped (defense in depth).
- **Lifecycle rides the status engine (Bi-D3):** every status move goes through
  ``status_machine.transition`` (no hardcoded status-key branch).
"""
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.dependencies import effective_permission_keys
from app.form_engine.validation import validate_submission
from app.models.catalog import Product
from app.models.status import Status
from app.models.user import User
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.services import status_machine
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)

BR_PROMOTE_PERMISSION = "ideation.business_requirements.promote"

# Warm-start title cap (AC-BI-32b) — a derived title truncates on a word
# boundary so a promoted BR never carries a runaway problem string as its name.
_TITLE_MAX = 80


def _truncate_title(text: str) -> str:
    """Collapse whitespace + truncate to a sensible title length on a word
    boundary (AC-BI-32b) — never "Untitled BR" when an idea's problem exists."""
    text = " ".join((text or "").split())
    if len(text) <= _TITLE_MAX:
        return text
    cut = text[:_TITLE_MAX].rsplit(" ", 1)[0].rstrip()
    return (cut or text[:_TITLE_MAX]) + "…"


def _field_labels(doc: Dict) -> Dict[str, str]:
    """``{answer_key: display label}`` from a stamped template doc — used to turn
    the promote gate's per-field error map into a human-facing missing-fields
    message (AC-BI-34b)."""
    from app.form_engine.schemas import FormDocument

    form = FormDocument.model_validate(doc)
    return {f.key: (f.label or f.key) for f in form.input_fields() if f.key}

from ..models import (
    BusinessRequirement,
    Idea,
    IdeaBusinessRequirement,
    IdeationArtifactTemplateVersion,
)
from ..schemas import (
    BusinessRequirementDetailOut,
    BusinessRequirementOut,
    BrTemplateVersionOut,
)
from .br_templates import (
    BR_TEMPLATE_KEY,
    active_version_number,
    get_stamped_doc,
    resolve_active_template,
)
from .ideas import IdeaReadService
from .statuses import (
    BR_ENTITY,
    BR_PROMOTE_EDGE_ID,
    br_status_id,
    initial_br_status_id,
)


class BusinessRequirementService:
    def __init__(self, db: Session):
        self.db = db
        self._reader = IdeaReadService(db)

    # ── helpers ───────────────────────────────────────────────────────────
    def _br_or_404(self, tenant_id: str, br_id: str) -> BusinessRequirement:
        br = (
            self.db.query(BusinessRequirement)
            .filter(
                BusinessRequirement.id == br_id,
                BusinessRequirement.tenant_id == tenant_id,
            )
            .first()
        )
        if br is None:
            raise HTTPException(404, "Business requirement not found.")
        return br

    def _product_or_422(self, tenant_id: str, product_id: str) -> Product:
        product = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )
        if product is None:
            raise HTTPException(
                422, "productId does not resolve to a product for this workspace."
            )
        return product

    def _validate_answers(
        self,
        br: BusinessRequirement,
        answers: Optional[Dict],
        *,
        enforce_required: bool = False,
    ) -> Dict:
        """Validate ``answers`` against the BR's STAMPED template version (never
        the active one) via ``form_engine``. 422 on any per-field error;
        persists the cleaned payload.

        ``enforce_required`` defaults to ``False`` (AC-BI-34b): a DRAFT BR holds
        PARTIAL answers — a blank required field is not a 422 on save (consistent
        with the grill's ``enforce_required=False`` partial emit). Type / format /
        choice-membership are always validated. ``required`` completeness is
        enforced ONLY at the promote gate (:meth:`_enforce_promote_completeness`)."""
        doc = get_stamped_doc(
            self.db, br.template_key, br.template_version, br.tenant_id
        )
        if doc is None:
            raise HTTPException(
                422,
                "The stamped template version could not be resolved.",
            )
        clean, errors = validate_submission(
            doc, answers or {}, enforce_required=enforce_required
        )
        if errors:
            raise HTTPException(422, detail={"fieldErrors": errors})
        return clean

    # ── reads ─────────────────────────────────────────────────────────────
    def _serialize(
        self,
        br: BusinessRequirement,
        products: Dict[str, Product],
        statuses: Dict[str, Status],
        idea_counts: Dict[str, int],
    ) -> BusinessRequirementOut:
        product = products.get(br.product_id)
        status = statuses.get(br.status_id)
        return BusinessRequirementOut(
            id=br.id,
            productId=br.product_id,
            productName=product.name if product else "Unknown product",
            status=status.key if status else "draft",
            statusLabel=status.label if status else "Draft",
            statusColor=status.color if status else "gray",
            templateKey=br.template_key,
            templateVersion=br.template_version,
            title=br.title or "",
            ideaCount=idea_counts.get(br.id, 0),
            createdAt=br.created_at,
            updatedAt=br.updated_at,
        )

    def _resolve_maps(self, brs: List[BusinessRequirement]):
        product_ids = {b.product_id for b in brs if b.product_id}
        status_ids = {b.status_id for b in brs if b.status_id}
        products = (
            {
                p.id: p
                for p in self.db.query(Product)
                .filter(Product.id.in_(product_ids))
                .all()
            }
            if product_ids
            else {}
        )
        statuses = (
            {
                s.id: s
                for s in self.db.query(Status).filter(Status.id.in_(status_ids)).all()
            }
            if status_ids
            else {}
        )
        return products, statuses

    def _idea_counts(self, brs: List[BusinessRequirement]) -> Dict[str, int]:
        if not brs:
            return {}
        br_ids = [b.id for b in brs]
        rows = (
            self.db.query(IdeaBusinessRequirement.business_requirement_id)
            .filter(IdeaBusinessRequirement.business_requirement_id.in_(br_ids))
            .all()
        )
        counts: Dict[str, int] = {}
        for (br_id,) in rows:
            counts[br_id] = counts.get(br_id, 0) + 1
        return counts

    def serialize_many(
        self, brs: List[BusinessRequirement]
    ) -> List[BusinessRequirementOut]:
        products, statuses = self._resolve_maps(brs)
        counts = self._idea_counts(brs)
        return [self._serialize(b, products, statuses, counts) for b in brs]

    def list(
        self,
        tenant_id: str,
        *,
        search: Optional[str] = None,
        filter: str = "active",
        product_id: Optional[str] = None,
    ) -> List[BusinessRequirementOut]:
        q = self.db.query(BusinessRequirement).filter(
            BusinessRequirement.tenant_id == tenant_id
        )
        if product_id:
            q = q.filter(BusinessRequirement.product_id == product_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(BusinessRequirement.title.ilike(like))

        mode = (filter or "active").lower()
        if mode in ("active", "archived"):
            archived_ids = [
                s.id
                for s in self.db.query(Status)
                .filter(
                    Status.entity_type == BR_ENTITY,
                    Status.is_archived.is_(True),
                )
                .all()
            ]
            if mode == "active" and archived_ids:
                q = q.filter(~BusinessRequirement.status_id.in_(archived_ids))
            elif mode == "archived":
                q = (
                    q.filter(BusinessRequirement.status_id.in_(archived_ids))
                    if archived_ids
                    else q.filter(False)
                )

        brs = q.order_by(
            BusinessRequirement.created_at.desc(), BusinessRequirement.id.desc()
        ).all()
        return self.serialize_many(brs)

    def get(self, tenant_id: str, br_id: str) -> BusinessRequirementDetailOut:
        br = self._br_or_404(tenant_id, br_id)
        base = self.serialize_many([br])[0]
        doc = get_stamped_doc(
            self.db, br.template_key, br.template_version, br.tenant_id
        )
        return BusinessRequirementDetailOut(
            **base.model_dump(),
            answers=dict(br.answers_json or {}),
            templateDoc=doc or {},
        )

    def linked_ideas(self, tenant_id: str, br_id: str) -> List:
        """The Ideas feeding this BR (AC-BI-17/35 lineage), tenant-scoped."""
        br = self._br_or_404(tenant_id, br_id)
        idea_ids = [
            r.idea_id
            for r in self.db.query(IdeaBusinessRequirement.idea_id).filter(
                IdeaBusinessRequirement.business_requirement_id == br.id,
                IdeaBusinessRequirement.tenant_id == tenant_id,
            )
        ]
        if not idea_ids:
            return []
        ideas = (
            self.db.query(Idea)
            .filter(Idea.id.in_(idea_ids), Idea.tenant_id == tenant_id)
            .order_by(Idea.created_at.desc(), Idea.id.desc())
            .all()
        )
        return self._reader.serialize_many(ideas)

    def template_versions(
        self, tenant_id: str, br_id: str
    ) -> List[BrTemplateVersionOut]:
        """The BR's template version history (Versions tab). Flags the version
        this BR STAMPED — historical BRs render against it forever (AC-BI-16)."""
        br = self._br_or_404(tenant_id, br_id)
        template = resolve_active_template(self.db, tenant_id)
        if template is None or template.template_key != br.template_key:
            return []
        rows = (
            self.db.query(IdeationArtifactTemplateVersion)
            .filter(IdeationArtifactTemplateVersion.template_id == template.id)
            .order_by(IdeationArtifactTemplateVersion.version.desc())
            .all()
        )
        return [
            BrTemplateVersionOut(
                version=v.version,
                isStamped=v.version == br.template_version,
                isActive=v.id == template.active_version_id,
                createdAt=v.created_at,
            )
            for v in rows
        ]

    # ── writes ────────────────────────────────────────────────────────────
    def create(
        self,
        tenant_id: str,
        *,
        product_id: str,
        title: str = "",
        answers: Optional[Dict] = None,
        idea_ids: Optional[List[str]] = None,
        actor: Optional[User] = None,
    ) -> BusinessRequirementDetailOut:
        """Create a ``draft`` BR that STAMPS the active template version, then
        validates ``answers`` against that stamped version (AC-BI-16). Optionally
        links ideas (validated tenant + same-product, AC-BI-17)."""
        self._product_or_422(tenant_id, product_id)
        template = resolve_active_template(self.db, tenant_id)
        version = active_version_number(template, self.db) if template else None
        if template is None or version is None:
            raise HTTPException(
                422, "No active Business Requirement template is configured."
            )
        initial_id = initial_br_status_id(self.db, tenant_id)
        if initial_id is None:
            raise HTTPException(422, "Business Requirement statuses are not seeded.")

        # Warm start (AC-BI-32b): a promote (idea_ids present) ABSORBS the idea —
        # derive a real title + pre-fill problem_statement so the BR opens titled
        # at 1/6 coverage, not "Untitled BR" at 0/6. The manual-dialog path (no
        # idea_ids) is unchanged: an explicit or blank title, no pre-fill.
        resolved_title = (title or "").strip()
        resolved_answers: Dict = dict(answers or {})
        if idea_ids:
            derived_title, derived_problem = self._absorb_ideas(tenant_id, idea_ids)
            if not resolved_title:
                resolved_title = derived_title
            existing_problem = str(resolved_answers.get("problem_statement") or "").strip()
            if derived_problem and not existing_problem:
                resolved_answers["problem_statement"] = derived_problem

        br = BusinessRequirement(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=initial_id,
            template_key=BR_TEMPLATE_KEY,
            template_version=version,
            title=resolved_title,
            answers_json=None,
            created_by=actor.id if actor else None,
            updated_by=actor.id if actor else None,
        )
        # Validate answers against the just-stamped version (partial answers are
        # valid on a draft — enforce_required=False by default, AC-BI-34b).
        br.answers_json = (
            self._validate_answers(br, resolved_answers) if resolved_answers else {}
        )
        self.db.add(br)
        self.db.flush()

        if idea_ids:
            self._link_ideas(tenant_id, br, idea_ids)

        self.db.commit()
        self.db.refresh(br)
        return self.get(tenant_id, br.id)

    def update(
        self,
        tenant_id: str,
        br_id: str,
        *,
        title: Optional[str] = None,
        answers: Optional[Dict] = None,
        actor: Optional[User] = None,
    ) -> BusinessRequirementDetailOut:
        """Edit the BR's title and/or ``answers_json`` (validated against the
        STAMPED version — a template edit never reshapes an existing BR)."""
        br = self._br_or_404(tenant_id, br_id)
        if title is not None:
            br.title = title.strip()
        if answers is not None:
            br.answers_json = self._validate_answers(br, answers)
        if actor:
            br.updated_by = actor.id
        self.db.commit()
        self.db.refresh(br)
        return self.get(tenant_id, br.id)

    def _absorb_ideas(self, tenant_id: str, idea_ids: List[str]) -> Tuple[str, str]:
        """Derive ``(title, problem_statement)`` from the ideas a promote absorbs
        (AC-BI-32b). Tenant-scoped. Title = the representative idea's problem
        (truncated); problem_statement = that problem, or all problems joined when
        several ideas are promoted together. The fuzzier idea fields
        (proposed_solution / impact / department / raw text) are DELIBERATELY not
        mapped here — they ride the grill's source context so the grill extracts
        them (avoids a wrong-guess mapping the user must correct)."""
        ordered = [i for i in dict.fromkeys(idea_ids) if i]
        if not ordered:
            return "", ""
        rows = {
            i.id: i
            for i in self.db.query(Idea)
            .filter(Idea.id.in_(ordered), Idea.tenant_id == tenant_id)
            .all()
        }
        problems = [
            p
            for i in ordered
            if i in rows and (p := (rows[i].problem or "").strip())
        ]
        if not problems:
            return "", ""
        problem_statement = problems[0] if len(problems) == 1 else "\n\n".join(problems)
        return _truncate_title(problems[0]), problem_statement

    def _link_ideas(
        self, tenant_id: str, br: BusinessRequirement, idea_ids: List[str]
    ) -> None:
        """Link ideas to a BR (AC-BI-17). Each idea must be in the caller's
        tenant AND on the SAME product as the BR (cross-tenant / cross-product =
        422 — the polymorphic-target rule). Idempotent per pair (unique)."""
        wanted = [i for i in dict.fromkeys(idea_ids) if i]
        if not wanted:
            return
        ideas = {
            i.id: i
            for i in self.db.query(Idea)
            .filter(Idea.id.in_(wanted), Idea.tenant_id == tenant_id)
            .all()
        }
        existing = {
            r.idea_id
            for r in self.db.query(IdeaBusinessRequirement.idea_id).filter(
                IdeaBusinessRequirement.business_requirement_id == br.id
            )
        }
        for idea_id in wanted:
            idea = ideas.get(idea_id)
            if idea is None:
                raise HTTPException(
                    422,
                    "One or more ideas do not exist for this workspace.",
                )
            if idea.product_id != br.product_id:
                raise HTTPException(
                    422,
                    "An idea can only be linked to a BR on the same product.",
                )
            if idea_id in existing:
                continue
            self.db.add(
                IdeaBusinessRequirement(
                    tenant_id=tenant_id,
                    idea_id=idea_id,
                    business_requirement_id=br.id,
                )
            )
        self.db.flush()

    def link_ideas(
        self, tenant_id: str, br_id: str, idea_ids: List[str]
    ) -> List:
        br = self._br_or_404(tenant_id, br_id)
        self._link_ideas(tenant_id, br, idea_ids)
        self.db.commit()
        return self.linked_ideas(tenant_id, br_id)

    def unlink_idea(self, tenant_id: str, br_id: str, idea_id: str) -> List:
        br = self._br_or_404(tenant_id, br_id)
        self.db.query(IdeaBusinessRequirement).filter(
            IdeaBusinessRequirement.business_requirement_id == br.id,
            IdeaBusinessRequirement.idea_id == idea_id,
            IdeaBusinessRequirement.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        self.db.commit()
        return self.linked_ideas(tenant_id, br_id)

    def _enforce_promote_gate(
        self,
        tenant_id: str,
        br: BusinessRequirement,
        target_id: str,
        actor: Optional[User],
    ) -> None:
        """If the move about to fire is the ``br-tr-promote`` edge (draft →
        ready), require ``.promote`` — the SEPARATE permission (AC-BI-19). Resolve
        the edge in the BR entity's resolved tier so a future tenant fork still
        matches its own promote edge."""
        tier = StatusRepository(self.db).resolve_tier(BR_ENTITY, tenant_id)
        edge = StatusTransitionRepository(self.db).find_edge(
            br.status_id, target_id, tier
        )
        if edge is None or edge.id != BR_PROMOTE_EDGE_ID:
            return
        held = effective_permission_keys(actor) if actor else set()
        if BR_PROMOTE_PERMISSION not in held:
            raise HTTPException(
                403,
                "You are not allowed to promote a business requirement to ready.",
            )
        # Completeness is enforced ONLY here (AC-BI-34/34b) — a draft saves
        # partial, but promote requires every required field present.
        self._enforce_promote_completeness(br)

    def _enforce_promote_completeness(self, br: BusinessRequirement) -> None:
        """Re-validate the BR's ``answers_json`` against its STAMPED template with
        ``required`` ENFORCED (AC-BI-34). A promote with missing required fields is
        refused with a friendly, specific message naming the blank field LABELS
        (AC-BI-34b) plus the per-field ``fieldErrors`` map (inline highlight)."""
        doc = get_stamped_doc(
            self.db, br.template_key, br.template_version, br.tenant_id
        )
        if doc is None:
            raise HTTPException(
                422, "The stamped template version could not be resolved."
            )
        _clean, errors = validate_submission(
            doc, br.answers_json or {}, enforce_required=True
        )
        if not errors:
            return
        labels = _field_labels(doc)
        # Preserve document order + de-dup for the human-facing list.
        missing: List[str] = []
        for key in errors:
            label = labels.get(key, key)
            if label not in missing:
                missing.append(label)
        raise HTTPException(
            422,
            detail={
                "fieldErrors": errors,
                "message": (
                    "Add the required fields before promoting: "
                    + ", ".join(missing)
                ),
            },
        )

    def set_status(
        self,
        tenant_id: str,
        br_id: str,
        status_key: str,
        actor: Optional[User],
    ) -> BusinessRequirementDetailOut:
        """Move the BR to ``status_key`` via the status engine (server-
        authoritative). Illegal move = 409; role-blocked = 403; unknown key =
        422. NEVER hardcode a status-key branch (DoD).

        The PROMOTE gate (AC-BI-19/34): firing the ``br-tr-promote`` (draft →
        ready) edge additionally requires ``ideation.business_requirements.
        promote`` — a ``.manage``-only actor is refused 403. Every OTHER BR edge
        stays gated by ``.manage`` (the router). The gate resolves the ACTUAL
        edge fired (by id, a code contract) — not the target status key — so a
        tenant renaming a status can't slip the gate, and the sibling
        ``grilling → ready`` edge is NOT promote-gated."""
        br = self._br_or_404(tenant_id, br_id)
        target_id = br_status_id(self.db, status_key, tenant_id)
        if target_id is None:
            raise HTTPException(422, f"Unknown BR status '{status_key}'.")
        self._enforce_promote_gate(tenant_id, br, target_id, actor)
        try:
            status_machine.transition(
                self.db, BR_ENTITY, br, target_id, actor=actor, tenant_id=tenant_id
            )
        except TransitionForbidden as exc:
            raise HTTPException(403, exc.message) from exc
        except (TransitionNotAllowed, TransitionConditionsNotMet) as exc:
            raise HTTPException(409, exc.message) from exc
        self.db.refresh(br)
        return self.get(tenant_id, br.id)

    def delete(self, tenant_id: str, br_id: str) -> None:
        br = self._br_or_404(tenant_id, br_id)
        self.db.query(IdeaBusinessRequirement).filter(
            IdeaBusinessRequirement.business_requirement_id == br.id
        ).delete(synchronize_session=False)
        self.db.delete(br)
        self.db.commit()
