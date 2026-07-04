"""Generic Review/Approval engine business logic (plan sprint-4/06 Part 2) —
Router → THIS → ReviewRepository. CORE; never imports the EMS module.

Owns:
- Config + roles + role-actors CRUD with validation (AC-06-29/36).
- The score-field guard (AC-06-36): a config's ``score_field_key`` must be a
  numeric field in the review form's PUBLISHED version.
- Author-actor capture/resolution (AC-06-41/42): a submission's author as an
  identity-agnostic ``(actor_kind, actor_id)`` ref, resolved tenant-scoped.
- Actor-source resolution (AC-06-30): RULE / EXPLICIT (in-engine) +
  PERSONA / STAFF_ROLE (via the injectable resolver hook — keeps core EMS-free).
- can_submit gate (AC-06-31).
- Decision write + first-wins (AC-06-34).
- Live average computed on read (AC-06-35).

The workflow ActionDefs (review.allocate / review.escalate) + the seeded default
workflow + firing the decision's status transition are PART B — this slice builds
the pure selection + the first-wins decision write + the live average that those
actions and the surfaces consume.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.form_engine.schemas import FormDocument, NUMERIC_FIELD_TYPES
from app.models.form import Form, FormSubmission, FormVersion
from app.models.review import (
    ACTOR_KINDS,
    ACTOR_SOURCES,
    ASSIGNMENT_COMPLETED,
    DECISION_ACCEPTED,
    DECISION_REJECTED,
    DECISION_REVISIONS,
    DECISIONS,
    SOURCE_EXPLICIT,
    SOURCE_PERSONA,
    SOURCE_RULE,
    SOURCE_STAFF_ROLE,
    ReviewConfiguration,
    ReviewDecision,
    ReviewRole,
    ReviewRoleActor,
)
from app.repositories.review_repository import ReviewRepository
from app.review_engine.resolvers import grant_actor_surface, resolve_actor_pool
from app.rule_engine.evaluator import collect_fact_keys, evaluate


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- service exceptions (router maps to HTTP) ----


class ReviewError(Exception):
    pass


class ReviewNotFound(ReviewError):
    pass


class ReviewValidationError(ReviewError):
    """Bad config/role input → 422."""


class ReviewDecisionConflict(ReviewError):
    """A decision already exists for (config, group, revision) → 409 (first-wins)."""


class ReviewTransitionUnavailable(ReviewError):
    """The decision's mapped target status is unreachable from the submission's
    CURRENT status (no edge configured, or its conditions fail) → 422. Raised
    BEFORE the decision row is written so a misconfigured status mapping never
    leaves an orphan decision (decided-but-not-moved)."""


class ReviewConfigService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ReviewRepository(db)

    # ---- form/version helpers (tenant-scoped, polymorphic-target_id rule) ----

    def _form(self, tenant_id: str, form_id: str) -> Optional[Form]:
        return (
            self.db.query(Form)
            .filter(Form.tenant_id == tenant_id, Form.id == form_id)
            .first()
        )

    def _published_doc(self, tenant_id: str, form_id: str) -> Optional[FormDocument]:
        """The form's CURRENT published version document, tenant-scoped via the
        join to forms — never resolve a version id unscoped. None when the form
        is unknown to the tenant or has never been published."""
        form = self._form(tenant_id, form_id)
        if form is None or not form.current_version_id:
            return None
        version = (
            self.db.query(FormVersion)
            .join(Form, Form.id == FormVersion.form_id)
            .filter(
                FormVersion.id == form.current_version_id,
                Form.tenant_id == tenant_id,
            )
            .first()
        )
        if version is None:
            return None
        try:
            return FormDocument.model_validate(version.definition_json)
        except Exception:  # noqa: BLE001 — a corrupt stored doc = no usable fields
            return None

    def _numeric_field_keys(self, doc: FormDocument) -> set:
        return {
            f.key
            for f in doc.input_fields()
            if f.key and f.type in NUMERIC_FIELD_TYPES
        }

    def _answer_field_keys(self, tenant_id: str, form_id: str) -> set:
        """Answer keys of the SUBMISSION form's published version — the universe a
        RULE role's conditions may reference (facts = ``answers.<key>``)."""
        doc = self._published_doc(tenant_id, form_id)
        if doc is None:
            return set()
        return {f.key for f in doc.input_fields() if f.key}

    # ---- editor metadata (the admin pickers — AC-06-55) ----

    # Form field type → rule-engine fact type, for the RULE-role condition
    # builder (facts = ``answers.<key>``). Unmapped types are omitted (the
    # builder only offers facts it can compare — foolproof-UI).
    _FACT_TYPE_BY_FIELD: Dict[str, str] = {
        "text": "string",
        "textarea": "string",
        "email": "string",
        "phone": "string",
        "url": "string",
        "number": "number",
        "integer": "number",
        "rating": "number",
        "computed": "number",
        "select": "enum",
        "radio": "enum",
        "multiselect": "list",
        "checkboxes": "list",
        "yesno": "boolean",
        "date": "date",
        "datetime": "date",
    }

    def form_meta(
        self,
        tenant_id: str,
        submission_form_id: Optional[str],
        review_form_id: Optional[str],
    ) -> Dict[str, Any]:
        """Picker universes for the Review-process admin (AC-06-55):

        - ``submission_statuses`` — the submission form's SCOPED status graph
          (the only valid targets for the 4 status-mapping selects).
        - ``numeric_fields`` — numeric fields of the review form's PUBLISHED
          version (the only valid ``score_field_key`` options).
        - ``submission_facts`` — answer facts of the submission form's published
          version (the RULE-role condition builder universe).

        Each id is validated tenant-scoped; an unknown/unpublished form simply
        yields an empty list (never a 404 — the form select itself is the guard).
        """
        statuses: List[Dict[str, Any]] = []
        submission_facts: List[Dict[str, Any]] = []
        if submission_form_id:
            from app.services.form_service import FormNotFound, FormService

            try:
                graph = FormService(self.db).submission_graph(tenant_id, submission_form_id)
                statuses = [
                    {"id": s["id"], "label": s["label"], "color": s.get("color") or ""}
                    for s in graph["statuses"]
                ]
            except FormNotFound:
                statuses = []
            doc = self._published_doc(tenant_id, submission_form_id)
            if doc is not None:
                for field in doc.input_fields():
                    fact_type = self._FACT_TYPE_BY_FIELD.get(field.type)
                    if not field.key or fact_type is None:
                        continue
                    fact: Dict[str, Any] = {
                        "key": f"answers.{field.key}",
                        "label": field.label or field.key,
                        "type": fact_type,
                    }
                    if fact_type in ("enum", "list") and field.options:
                        fact["options"] = [
                            {"value": item.value, "label": item.label}
                            for item in field.options.items
                        ]
                    submission_facts.append(fact)

        numeric_fields: List[Dict[str, Any]] = []
        if review_form_id:
            doc = self._published_doc(tenant_id, review_form_id)
            if doc is not None:
                numeric = self._numeric_field_keys(doc)
                numeric_fields = [
                    {"key": f.key, "label": f.label or f.key}
                    for f in doc.input_fields()
                    if f.key and f.key in numeric
                ]

        return {
            "submission_statuses": statuses,
            "numeric_fields": numeric_fields,
            "submission_facts": submission_facts,
        }

    # ---- mapping (camelCase out) ----

    def config_to_dict(self, config: ReviewConfiguration) -> Dict[str, Any]:
        roles = self.repo.list_roles(config.tenant_id, config.id)
        return {
            "id": config.id,
            "name": config.name,
            "form_id": config.form_id,
            "review_form_id": config.review_form_id,
            "required_review_count": config.required_review_count,
            "score_field_key": config.score_field_key,
            "context_type": config.context_type,
            "context_id": config.context_id,
            "window_start": config.window_start,
            "window_end": config.window_end,
            "review_start_status_id": config.review_start_status_id,
            "revisions_status_id": config.revisions_status_id,
            "accepted_status_id": config.accepted_status_id,
            "rejected_status_id": config.rejected_status_id,
            "is_active": config.is_active,
            "roles": [self.role_to_dict(r) for r in roles],
            "created_at": config.created_at,
            "updated_at": config.updated_at,
        }

    def role_to_dict(self, role: ReviewRole) -> Dict[str, Any]:
        actors = self.repo.list_actors(role.tenant_id, role.id)
        return {
            "id": role.id,
            "review_configuration_id": role.review_configuration_id,
            "key": role.key,
            "label": role.label,
            "can_submit": role.can_submit,
            "can_review": role.can_review,
            "can_decide": role.can_decide,
            "actor_source": role.actor_source,
            "actor_identity_kind": role.actor_identity_kind,
            "bound_persona_id": role.bound_persona_id,
            "bound_staff_role_id": role.bound_staff_role_id,
            "conditions_json": role.conditions_json,
            "sort_order": role.sort_order,
            "actors": [
                {
                    "id": a.id,
                    "actor_kind": a.actor_kind,
                    "actor_id": a.actor_id,
                    "conditions_json": a.conditions_json,
                    "sort_order": a.sort_order,
                }
                for a in actors
            ],
        }

    # ---- config CRUD ----

    def list_configs(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [self.config_to_dict(c) for c in self.repo.list_configs(tenant_id)]

    def get_config(self, tenant_id: str, config_id: str) -> ReviewConfiguration:
        config = self.repo.get_config(tenant_id, config_id)
        if config is None:
            raise ReviewNotFound()
        return config

    def create_config(self, tenant_id: str, *, roles: Optional[List[Dict[str, Any]]] = None, **values) -> ReviewConfiguration:
        name = (values.get("name") or "").strip()
        if not name:
            raise ReviewValidationError("A name is required.")
        form_id = values.get("form_id")
        review_form_id = values.get("review_form_id")
        if not form_id or self._form(tenant_id, form_id) is None:
            raise ReviewValidationError("The submission form is unknown.")
        if not review_form_id or self._form(tenant_id, review_form_id) is None:
            raise ReviewValidationError("The review form is unknown.")

        score_field_key = values.get("score_field_key")
        self._guard_score_field(tenant_id, review_form_id, score_field_key)

        config = ReviewConfiguration(
            tenant_id=tenant_id,
            name=name,
            form_id=form_id,
            review_form_id=review_form_id,
            required_review_count=int(values.get("required_review_count") or 1),
            score_field_key=score_field_key,
            context_type=values.get("context_type"),
            context_id=values.get("context_id"),
            window_start=values.get("window_start"),
            window_end=values.get("window_end"),
            review_start_status_id=values.get("review_start_status_id"),
            revisions_status_id=values.get("revisions_status_id"),
            accepted_status_id=values.get("accepted_status_id"),
            rejected_status_id=values.get("rejected_status_id"),
            is_active=bool(values.get("is_active", True)),
        )
        self.repo.add_config(config)
        for spec in roles or []:
            self._create_role(tenant_id, config, spec)
        self.db.commit()
        self.db.refresh(config)
        # Auto-scaffold + publish the default allocate workflow (AC-06-32). The
        # "Submitted into review-start" transition then fires it → review.allocate.
        # Failure-isolated: a workflow hiccup never blocks the config create.
        self._ensure_allocate_workflow(tenant_id, config)
        return config

    # ---- seeded allocate workflow (AC-06-32) ----

    _ALLOCATE_WF_TAG = "review.allocate.config"

    def _ensure_allocate_workflow(self, tenant_id: str, config: ReviewConfiguration) -> None:
        """Idempotently create + publish a workflow wired to ``status_changed →
        review_start_status_id`` on the ``form_submission`` entity, with one
        ``review.allocate`` node bound to this config. Needs a
        ``review_start_status_id`` to wire the trigger; without one (config drafted
        before the rubric/flow is final) we skip — re-run on the first update that
        sets it. Idempotent via a sentinel description tag.

        Built through ``WorkflowService.create`` + ``publish`` so publish
        denormalizes ``trigger_type``/``trigger_entity_type=form_submission``/
        ``toStatus`` (the indexed ``entity_events`` match)."""
        if not config.review_start_status_id:
            return
        try:
            from app.models.form import FORM_SUBMISSION_ENTITY
            from app.models.workflow import Workflow
            from app.services.workflow_service import WorkflowService

            tag = f"{self._ALLOCATE_WF_TAG}:{config.id}"
            existing = (
                self.db.query(Workflow)
                .filter(
                    Workflow.tenant_id == tenant_id,
                    Workflow.description == tag,
                    Workflow.is_trashed.is_(False),
                )
                .first()
            )
            if existing is not None:
                return

            trigger_id = "trigger"
            action_id = "allocate"
            draft = {
                "schemaVersion": 1,
                "nodes": [
                    {
                        "id": trigger_id,
                        "kind": "trigger",
                        "type": "entity.status_changed",
                        "name": "Submitted for review",
                        "position": {"x": 0, "y": 0},
                        "config": {
                            "entityType": FORM_SUBMISSION_ENTITY,
                            "toStatus": config.review_start_status_id,
                        },
                    },
                    {
                        "id": action_id,
                        "kind": "action",
                        "type": "review.allocate",
                        "name": "Allocate reviewers",
                        "position": {"x": 0, "y": 200},
                        "config": {"reviewConfigurationId": config.id},
                    },
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": trigger_id,
                        "target": action_id,
                        "sourcePort": "out",
                    }
                ],
            }
            wf_service = WorkflowService(self.db)
            wf = wf_service.create(
                tenant_id,
                name=f"Allocate reviewers — {config.name}",
                description=tag,
                draft=draft,
                actor_id="",
            )
            wf_service.publish(wf.id, tenant_id, actor_id="")
            # Workflows are created inactive (is_active default False) and only
            # fire when active — activate the seeded allocate workflow so the
            # Submitted transition triggers it (AC-06-04/32).
            wf_service.set_active(wf.id, tenant_id, True)
        except Exception:  # noqa: BLE001 — never block config create on the workflow
            self.db.rollback()

    def update_config(
        self, tenant_id: str, config_id: str, *, fields_set: set, roles: Optional[List[Dict[str, Any]]] = None, **values
    ) -> ReviewConfiguration:
        config = self.get_config(tenant_id, config_id)

        review_form_id = values.get("review_form_id") if "review_form_id" in fields_set else config.review_form_id
        if "review_form_id" in fields_set and values.get("review_form_id"):
            if self._form(tenant_id, values["review_form_id"]) is None:
                raise ReviewValidationError("The review form is unknown.")
            config.review_form_id = values["review_form_id"]
        if "form_id" in fields_set and values.get("form_id"):
            if self._form(tenant_id, values["form_id"]) is None:
                raise ReviewValidationError("The submission form is unknown.")
            config.form_id = values["form_id"]
        if "name" in fields_set and values.get("name") is not None:
            config.name = values["name"].strip()
        if "required_review_count" in fields_set and values.get("required_review_count") is not None:
            config.required_review_count = int(values["required_review_count"])
        if "score_field_key" in fields_set:
            self._guard_score_field(tenant_id, review_form_id, values.get("score_field_key"))
            config.score_field_key = values.get("score_field_key")
        for col in ("window_start", "window_end", "review_start_status_id",
                    "revisions_status_id", "accepted_status_id", "rejected_status_id",
                    "context_type", "context_id"):
            if col in fields_set:
                setattr(config, col, values.get(col))
        if "is_active" in fields_set and values.get("is_active") is not None:
            config.is_active = bool(values["is_active"])

        # Replace-all roles when provided (the form posts the whole role set).
        if roles is not None:
            self.repo.delete_roles_for_config(tenant_id, config_id)
            self.db.flush()
            for spec in roles:
                self._create_role(tenant_id, config, spec)

        self.db.commit()
        self.db.refresh(config)
        # A config that just gained its review_start_status_id now scaffolds the
        # allocate workflow (idempotent — no-op when already created, AC-06-32).
        self._ensure_allocate_workflow(tenant_id, config)
        return config

    def delete_config(self, tenant_id: str, config_id: str) -> None:
        config = self.get_config(tenant_id, config_id)
        self.repo.delete_roles_for_config(tenant_id, config_id)
        self.repo.delete_config(config)
        self.db.commit()

    # ---- score-field guard (AC-06-36) ----

    def _guard_score_field(self, tenant_id: str, review_form_id: str, score_field_key: Optional[str]) -> None:
        """422 unless ``score_field_key`` is a numeric field in the review form's
        PUBLISHED version. A None/blank key is allowed (a config can be drafted
        before the rubric is final — allocation/average just have nothing to
        average until it is set)."""
        if not score_field_key:
            return
        doc = self._published_doc(tenant_id, review_form_id)
        if doc is None:
            raise ReviewValidationError(
                "The review form has no published version to validate the score field against."
            )
        if score_field_key not in self._numeric_field_keys(doc):
            raise ReviewValidationError(
                f"Score field '{score_field_key}' is not a numeric field of the review form."
            )

    # ---- role validation + create (AC-06-29) ----

    def _create_role(self, tenant_id: str, config: ReviewConfiguration, spec: Dict[str, Any]) -> ReviewRole:
        key = (spec.get("key") or "").strip()
        label = (spec.get("label") or "").strip()
        if not key:
            raise ReviewValidationError("A role needs a key.")
        if not label:
            raise ReviewValidationError("A role needs a label.")

        identity_kind = spec.get("actor_identity_kind")
        if identity_kind not in ACTOR_KINDS:
            raise ReviewValidationError(
                f"Role '{key}' needs a valid identity kind (user|profile)."
            )
        source = spec.get("actor_source")
        if source not in ACTOR_SOURCES:
            raise ReviewValidationError(
                f"Role '{key}' needs a valid actor source."
            )

        conditions = spec.get("conditions_json")
        if source == SOURCE_RULE and conditions is not None:
            problems = self._validate_submission_conditions(tenant_id, config.form_id, conditions)
            if problems:
                raise ReviewValidationError(
                    f"Role '{key}' conditions: " + "; ".join(problems)
                )
        if source == SOURCE_PERSONA and not spec.get("bound_persona_id"):
            raise ReviewValidationError(
                f"Role '{key}' is a persona role but no persona is bound."
            )
        if source == SOURCE_STAFF_ROLE and not spec.get("bound_staff_role_id"):
            raise ReviewValidationError(
                f"Role '{key}' is a staff-role role but no staff role is bound."
            )

        role = ReviewRole(
            tenant_id=tenant_id,
            review_configuration_id=config.id,
            key=key,
            label=label,
            can_submit=bool(spec.get("can_submit")),
            can_review=bool(spec.get("can_review")),
            can_decide=bool(spec.get("can_decide")),
            actor_source=source,
            actor_identity_kind=identity_kind,
            bound_persona_id=spec.get("bound_persona_id") if source == SOURCE_PERSONA else None,
            bound_staff_role_id=spec.get("bound_staff_role_id") if source == SOURCE_STAFF_ROLE else None,
            conditions_json=conditions if source == SOURCE_RULE else None,
            sort_order=int(spec.get("sort_order") or 0),
        )
        self.repo.add_role(role)

        # Named candidates (EXPLICIT / RULE) — each candidate's kind MUST match
        # the role's uniform identity kind (AC-06-29/30).
        if source in (SOURCE_EXPLICIT, SOURCE_RULE):
            for i, a in enumerate(spec.get("actors") or []):
                actor_kind = a.get("actor_kind")
                actor_id = a.get("actor_id")
                if actor_kind != identity_kind:
                    raise ReviewValidationError(
                        f"Role '{key}' candidate kind '{actor_kind}' must match the "
                        f"role's identity kind '{identity_kind}'."
                    )
                if not actor_id:
                    raise ReviewValidationError(f"Role '{key}' has a candidate without an id.")
                self.repo.add_actor(
                    ReviewRoleActor(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        conditions_json=a.get("conditions_json"),
                        sort_order=int(a.get("sort_order") or i),
                    )
                )
                # AC-06-22 — an EXPLICIT profile actor BOUND to a review role
                # auto-acquires the surface(s) matching the role's capabilities so
                # it can see its work in the portal immediately on config save.
                # This is the load-bearing path for can_decide / can_submit actors:
                # deciders/submitters have NO assignment row (allocate only creates
                # reviewer assignments), so without this they'd never get the
                # surface key. Reviewers are covered here too (idempotent; allocate
                # also grants them). EXPLICIT only — RULE candidates are conditional
                # and only gain visibility when actually allocated; user-kind actors
                # use the staff surface (core perms), never persona-granted.
                if source == SOURCE_EXPLICIT and actor_kind == "profile":
                    self._grant_role_surfaces(tenant_id, config, role, actor_id)
        return role

    # ---- surface auto-grant for bound EXPLICIT profile actors (AC-06-22) ----

    # role capability flag → portal surface capability token.
    _ROLE_CAPABILITIES = [
        ("can_submit", "submit"),
        ("can_review", "review"),
        ("can_decide", "decide"),
    ]

    def _grant_role_surfaces(
        self, tenant_id: str, config: ReviewConfiguration, role: ReviewRole, profile_id: str
    ) -> None:
        """Grant a bound EXPLICIT profile actor every portal surface its role
        confers (can_submit→submit, can_review→review, can_decide→decide), scoped
        to the config's context. Failure-isolated via grant_actor_surface (a grant
        hiccup never breaks config save)."""
        for flag, capability in self._ROLE_CAPABILITIES:
            if getattr(role, flag, False):
                grant_actor_surface(
                    self.db,
                    tenant_id,
                    profile_id=profile_id,
                    capability=capability,
                    context_type=config.context_type,
                    context_id=config.context_id,
                )

    def _validate_submission_conditions(
        self, tenant_id: str, form_id: str, conditions: Dict[str, Any]
    ) -> List[str]:
        """RULE-role conditions reference ``answers.<key>`` facts of the SUBMISSION
        form — these are DYNAMIC per-document, not a registered FactSource, so we
        do NOT call ``rule_engine.schemas.validate_tree`` (it operates over the
        code-side fact registry). Instead — mirroring ``validate_form_doc`` — we
        check structure (it's a group) and that every referenced fact is an
        ``answers.<key>`` of a real published-version field. Runtime stays
        fail-closed for stale trees."""
        problems: List[str] = []
        if not isinstance(conditions, dict) or conditions.get("kind") != "group":
            return ["conditions must be a group."]
        valid = {f"answers.{k}" for k in self._answer_field_keys(tenant_id, form_id)}
        for fact in collect_fact_keys(conditions):
            if fact not in valid:
                bare = fact[len("answers."):] if fact.startswith("answers.") else fact
                problems.append(f"references '{bare}', which is not a submission field.")
        return problems

    # ---- author-actor capture (AC-06-41/42) ----

    def submission_author_actor(self, submission: FormSubmission) -> Optional[Tuple[str, str]]:
        """The submission's author as an identity-agnostic actor ref, or None for
        an anonymous submission. A Profile submitter is captured via the inbound
        polymorphic subject (``subject_type='profile'``/``subject_id``); a staff
        submitter is ``user_id``. Resolve TENANT-SCOPED at use (the caller passes
        a tenant-scoped submission; the actor id is further scoped when the
        consumer loads the Profile/User)."""
        if submission.subject_type == "profile" and submission.subject_id:
            return ("profile", submission.subject_id)
        if submission.user_id:
            return ("user", submission.user_id)
        return None

    # ---- actor-source resolution (AC-06-30) ----

    def resolve_role_candidates(
        self,
        tenant_id: str,
        config: ReviewConfiguration,
        role: ReviewRole,
        submission: FormSubmission,
        revision: int,
    ) -> List[Tuple[str, str]]:
        """PURE selection (no writes) of a role's candidate actors for a
        submission. The CALLER (Part B's allocate) trims to first-N up to
        ``required_review_count`` and creates assignments. The author is always
        excluded (AC-06-32/42).

        - RULE: the role's ``conditions_json`` gates whether the role allocates at
          all for this submission (facts = ``answers.<key>``, fail-closed). If it
          passes, candidates = the role's named actors ordered by ``sort_order``,
          each further-gated by its own ``conditions_json`` (null = pass).
        - EXPLICIT: the role's named actors ordered by ``sort_order`` (no role gate).
        - PERSONA / STAFF_ROLE: the injectable resolver hook (keeps core EMS-free).
        """
        author = self.submission_author_actor(submission)

        def _exclude_author(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return [p for p in pairs if p != author]

        if role.actor_source == SOURCE_RULE:
            facts = self._submission_answer_facts(submission, role.conditions_json)
            if not evaluate(role.conditions_json, facts):
                return []
            candidates: List[Tuple[str, str]] = []
            for a in self.repo.list_actors(tenant_id, role.id):
                if a.conditions_json is not None:
                    a_facts = self._submission_answer_facts(submission, a.conditions_json)
                    if not evaluate(a.conditions_json, a_facts):
                        continue
                candidates.append((a.actor_kind, a.actor_id))
            return _exclude_author(candidates)

        if role.actor_source == SOURCE_EXPLICIT:
            return _exclude_author(
                [(a.actor_kind, a.actor_id) for a in self.repo.list_actors(tenant_id, role.id)]
            )

        # PERSONA / STAFF_ROLE — pool from the injectable resolver (fail-closed [] when none).
        return _exclude_author(resolve_actor_pool(self.db, tenant_id, role, submission))

    def _submission_answer_facts(
        self, submission: FormSubmission, conditions: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Flatten the submission's answers into ``answers.<key>`` facts for the
        rule evaluator — only the keys the tree actually reads (perf, mirrors the
        form-engine ``resolve_facts`` only_keys pattern)."""
        answers = submission.answers_json or {}
        needed = collect_fact_keys(conditions)
        facts: Dict[str, Any] = {}
        for fact in needed:
            if fact.startswith("answers."):
                facts[fact] = answers.get(fact[len("answers."):])
        return facts

    # ---- can_submit gate (AC-06-31) ----

    def may_submit(
        self, tenant_id: str, config: ReviewConfiguration, actor_kind: str, actor_id: str
    ) -> bool:
        """True iff the actor holds a ``can_submit`` role for the config. EXPLICIT
        membership = named actor; PERSONA/STAFF_ROLE = the resolver pool contains
        the actor. The actor's kind must match the role's identity kind."""
        for role in self.repo.list_roles(tenant_id, config.id):
            if not role.can_submit or role.actor_identity_kind != actor_kind:
                continue
            if role.actor_source in (SOURCE_EXPLICIT, SOURCE_RULE):
                if any(
                    a.actor_kind == actor_kind and a.actor_id == actor_id
                    for a in self.repo.list_actors(tenant_id, role.id)
                ):
                    return True
            else:  # PERSONA / STAFF_ROLE — submission=None (membership-only check)
                pool = resolve_actor_pool(self.db, tenant_id, role, None)
                if (actor_kind, actor_id) in pool:
                    return True
        return False

    def may_decide(
        self, tenant_id: str, config: ReviewConfiguration, actor_kind: str, actor_id: str
    ) -> bool:
        """True iff the actor holds a ``can_decide`` role for the config (AC-06-34
        — any can_decide actor may decide, first-wins). Same resolution as
        ``may_submit`` over the can_decide capability."""
        for role in self.repo.list_roles(tenant_id, config.id):
            if not role.can_decide or role.actor_identity_kind != actor_kind:
                continue
            if role.actor_source in (SOURCE_EXPLICIT, SOURCE_RULE):
                if any(
                    a.actor_kind == actor_kind and a.actor_id == actor_id
                    for a in self.repo.list_actors(tenant_id, role.id)
                ):
                    return True
            else:  # PERSONA / STAFF_ROLE — membership-only check
                pool = resolve_actor_pool(self.db, tenant_id, role, None)
                if (actor_kind, actor_id) in pool:
                    return True
        return False

    def configs_for_decider(
        self, tenant_id: str, actor_kind: str, actor_id: str
    ) -> List[ReviewConfiguration]:
        """Every config for which the actor holds a ``can_decide`` role — backs
        the Decisions surface (AC-06-45/07)."""
        return [
            c
            for c in self.repo.list_configs(tenant_id)
            if self.may_decide(tenant_id, c, actor_kind, actor_id)
        ]

    # ---- decision write + first-wins (AC-06-34) ----

    def decide(
        self,
        tenant_id: str,
        config: ReviewConfiguration,
        group_id: str,
        revision: int,
        decider_kind: str,
        decider_id: str,
        decision: str,
        feedback: Optional[str] = None,
    ) -> ReviewDecision:
        """Write the terminal decision IFF none exists yet for (config, group,
        revision) — single decider, first-wins. A concurrent second attempt
        raises ReviewDecisionConflict (→ 409), NOT a double write (the DB UNIQUE
        is the backstop). Firing the status transition is the CALLER's job
        (Part B / slice 2) — this returns the written decision."""
        if decision not in DECISIONS:
            raise ReviewValidationError(f"Unknown decision '{decision}'.")
        # Fast-path check (clean 409 without an IntegrityError when uncontended).
        if self.repo.get_decision(tenant_id, config.id, group_id, revision) is not None:
            raise ReviewDecisionConflict()
        row = ReviewDecision(
            tenant_id=tenant_id,
            review_configuration_id=config.id,
            reviewed_submission_group_id=group_id,
            revision_number=revision,
            decider_kind=decider_kind,
            decider_id=decider_id,
            decision=decision,
            feedback_text=(feedback or None),
        )
        try:
            self.repo.add_decision(row)
            self.db.commit()
        except IntegrityError:
            # A concurrent decider won the race (the UNIQUE fired) — no-op.
            self.db.rollback()
            raise ReviewDecisionConflict()
        self.db.refresh(row)
        return row

    # ---- decision → status transition (Part B, AC-06-34 completion) ----

    def _current_submission(
        self, tenant_id: str, group_id: str
    ) -> Optional[FormSubmission]:
        """The ``is_current`` row of the submission group, tenant-scoped — the
        live submission the decision transitions (plan-04 stable identity)."""
        return (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.submission_group_id == group_id,
                FormSubmission.is_current.is_(True),
            )
            .first()
        )

    def _decision_target_status(
        self, config: ReviewConfiguration, decision: str
    ) -> Optional[str]:
        return {
            DECISION_ACCEPTED: config.accepted_status_id,
            DECISION_REJECTED: config.rejected_status_id,
            DECISION_REVISIONS: config.revisions_status_id,
        }.get(decision)

    def decide_and_transition(
        self,
        tenant_id: str,
        config: ReviewConfiguration,
        group_id: str,
        revision: int,
        decider_kind: str,
        decider_id: str,
        decision: str,
        feedback: Optional[str] = None,
        actor: Optional[Any] = None,
    ) -> ReviewDecision:
        """Write the first-wins decision (``decide``) AND — only if it wrote —
        fire the mapped status transition on the group's CURRENT submission
        (ACCEPTED→accepted, REJECTED→rejected, REVISIONS→revisions). A second
        concurrent decide raises ReviewDecisionConflict (→ 409, no double
        transition). The status move goes through the ONE executor
        (``status_machine.transition``) so it re-emits ``status_changed`` (e.g. a
        Revisions move re-arms the revise loop, AC-06-09).

        Order = validate → (decision write + transition): the transition is
        PRE-VALIDATED (read-only) against the submission's CURRENT status BEFORE
        ``decide`` writes anything, so the common misconfig path (a mapped target
        with no edge from the current status) raises ``ReviewTransitionUnavailable``
        (→ 422) and leaves NO orphan decision row. Only once the move is known to
        be possible do we write the first-wins decision then fire the transition;
        a second concurrent decide still raises ``ReviewDecisionConflict`` (→ 409).

        ``decide`` commits the decision; the transition then commits its own unit
        (record + outbox atomically). NOTE the rare post-commit race: if the edge
        is torn down between pre-validation and fire, the transition raise is
        caught + re-raised as ``ReviewTransitionUnavailable`` — at that point the
        decision row has already committed (the unavoidable race edge). The
        pre-validation is the primary guard so the misconfig path never writes."""
        from app.models.form import FORM_SUBMISSION_ENTITY
        from app.services import status_machine
        from app.services.status_machine import (
            TransitionConditionsNotMet,
            TransitionForbidden,
            TransitionNotAllowed,
        )

        # First-wins takes precedence over transition pre-validation: if a
        # decision already exists for (config, group, revision) this is a 409,
        # NOT a 422 — and the submission may already sit at a terminal status
        # from the winning decision (which would otherwise fail pre-validation).
        if self.repo.get_decision(tenant_id, config.id, group_id, revision) is not None:
            raise ReviewDecisionConflict()

        target = self._decision_target_status(config, decision)
        submission = self._current_submission(tenant_id, group_id)
        move_required = (
            target is not None
            and submission is not None
            and submission.status_id != target
        )

        # Pre-validate the transition BEFORE writing the decision (no orphan on
        # a misconfigured status mapping). The move is possible only when an edge
        # from the current status to the target is fireable for this actor (role
        # + rule-engine conditions checked) — exactly what the executor will fire.
        if move_required:
            fireable = status_machine.available_transitions(
                self.db,
                FORM_SUBMISSION_ENTITY,
                submission,
                actor=actor,
                tenant_id=tenant_id,
            )
            if not any(e.to_status_id == target for e in fireable):
                raise ReviewTransitionUnavailable(
                    "Can't move the submission to the decision's mapped status — "
                    "no transition is configured from its current status. Check "
                    "the review process's status mapping."
                )

        row = self.decide(
            tenant_id, config, group_id, revision, decider_kind, decider_id, decision, feedback
        )
        # The decision is now committed (first-wins). Fire the pre-validated move.
        if move_required:
            try:
                status_machine.transition(
                    self.db,
                    FORM_SUBMISSION_ENTITY,
                    submission,
                    target,
                    actor=actor,
                    tenant_id=tenant_id,
                )
            except (
                TransitionNotAllowed,
                TransitionForbidden,
                TransitionConditionsNotMet,
            ) as exc:
                # Race edge: the edge was torn down after pre-validation. The
                # decision already committed (first-wins is honored); surface a
                # clean 422 instead of a 500. Never re-orphan as a 500.
                self.db.rollback()
                raise ReviewTransitionUnavailable(str(exc)) from exc
        return row

    # ---- live average (AC-06-35) ----

    def average_score(
        self, tenant_id: str, config: ReviewConfiguration, group_id: str, revision: int
    ) -> Optional[float]:
        """Average of ``score_field_key`` over COMPLETED assignments' review
        submissions — computed on READ (no stored column). Each review reads its
        OWN pinned-version answer. Partial allowed; None when no completed review
        carries a numeric score. Review submissions are resolved TENANT-SCOPED
        (the polymorphic-target_id rule)."""
        if not config.score_field_key:
            return None
        assignments = self.repo.list_assignments_for_revision(
            tenant_id, config.id, group_id, revision
        )
        review_ids = [
            a.review_submission_id
            for a in assignments
            if a.status == ASSIGNMENT_COMPLETED and a.review_submission_id
        ]
        if not review_ids:
            return None
        rows = (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.id.in_(review_ids),
            )
            .all()
        )
        scores: List[float] = []
        for sub in rows:
            value = (sub.answers_json or {}).get(config.score_field_key)
            num = _as_number(value)
            if num is not None:
                scores.append(num)
        if not scores:
            return None
        return sum(scores) / len(scores)


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
