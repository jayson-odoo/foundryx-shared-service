"""Notify-on-transition dispatch (sprint-2/01 D6).

Resolves a spec's recipients (USER / ROLE / DYNAMIC), renders the inline
merge-field template, and enqueues EMAIL via the plan-09 outbox. ``IN_APP`` is
modeled but inert (no-op + log — inbox UI is follow-up backlog). Never sends
directly — outbox always.

Merge fields: ``{{entityLabel}} {{recordLabel}} {{fromStatus}} {{toStatus}}
{{transitionLabel}} {{actorName}}`` — unknown fields render empty.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.notification_spec import (
    CHANNEL_EMAIL,
    DYNAMIC_ACTOR,
    DYNAMIC_ASSIGNEE,
    DYNAMIC_RECORD_OWNER,
    NotificationSpec,
    TARGET_DYNAMIC,
    TARGET_ROLE,
    TARGET_USER,
)
from app.models.role import Role
from app.models.tenant import PLATFORM_TENANT_ID
from app.models.user import User, UserStatus
from app.services.email_service import email_service
from app.template_engine import render_email as engine_render

logger = logging.getLogger("foundryx.status_engine")

_MERGE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_inline(template: str, context: Dict[str, Any]) -> str:
    return _MERGE_RE.sub(lambda m: str(context.get(m.group(1), "")), template or "")


def _active_user(db: Session, user_id: Optional[str], tenant_id: str) -> Optional[User]:
    """Tenant-scoped on purpose — recipient resolution must never cross a
    tenant boundary, even off a corrupt/planted id (code-review fix)."""
    if not user_id:
        return None
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id)
        .first()
    )
    if user is None or user.status != UserStatus.ACTIVE.value or not user.email:
        return None
    return user


def resolve_recipients(
    db: Session,
    spec: NotificationSpec,
    record: Any,
    actor: Optional[User],
) -> List[User]:
    """Recipient users for a spec — deduped, ACTIVE only, unresolvable skipped.

    Scoping (defense-in-depth; the service also validates at save):
      USER/ROLE → the spec AUTHOR's tier (platform tier = the platform tenant);
      DYNAMIC assignee/owner → the RECORD's tenant; actor → the actor's own.
    """
    author_tenant = spec.tenant_id or PLATFORM_TENANT_ID
    record_tenant = getattr(record, "tenant_id", None) or author_tenant
    users: Dict[str, User] = {}
    for recipient in spec.recipients:
        resolved: List[User] = []
        if recipient.target_type == TARGET_USER:
            user = _active_user(db, recipient.target_id, author_tenant)
            if user:
                resolved = [user]
        elif recipient.target_type == TARGET_ROLE:
            if recipient.target_id:
                resolved = [
                    u
                    for u in db.query(User)
                    .join(User.roles)
                    .filter(
                        Role.id == recipient.target_id,
                        Role.tenant_id == author_tenant,
                        User.tenant_id == author_tenant,
                    )
                    .all()
                    if u.status == UserStatus.ACTIVE.value and u.email
                ]
        elif recipient.target_type == TARGET_DYNAMIC:
            if recipient.dynamic_key == DYNAMIC_ACTOR and actor is not None:
                user = _active_user(db, actor.id, actor.tenant_id)
                if user:
                    resolved = [user]
            elif recipient.dynamic_key == DYNAMIC_ASSIGNEE:
                user = _active_user(db, getattr(record, "assignee_id", None), record_tenant)
                if user:
                    resolved = [user]
            elif recipient.dynamic_key == DYNAMIC_RECORD_OWNER:
                user = _active_user(db, getattr(record, "owner_id", None), record_tenant)
                if user:
                    resolved = [user]
        for user in resolved:
            users[user.id] = user
    return list(users.values())


def dispatch_specs(
    db: Session,
    specs: List[NotificationSpec],
    *,
    record: Any,
    actor: Optional[User],
    tenant_id: str,
    context: Dict[str, Any],
) -> int:
    """Render + enqueue every spec. Returns emails enqueued. No commit — the
    status machine owns the transaction (transition + emails land together)."""
    enqueued = 0
    for spec in specs:
        recipients = resolve_recipients(db, spec, record, actor)
        if not recipients:
            continue
        if spec.channel != CHANNEL_EMAIL:
            # IN_APP modeled inert (D6) — inbox dispatch is follow-up backlog.
            logger.info(
                "in-app notification skipped (inert channel): spec=%s recipients=%d",
                spec.id,
                len(recipients),
            )
            continue
        # Per-use template copy (plan 10 follow-up): the operator picked a
        # template and edited the wording — render the stored doc branded.
        if spec.doc_json:
            from app.template_engine import render_email_doc

            facts = {str(k): str(v) for k, v in context.items()}
            for user in recipients:
                try:
                    rendered = render_email_doc(
                        db,
                        doc_json=spec.doc_json,
                        subject=spec.template_subject,
                        context="status.notification",
                        tenant_id=tenant_id,
                        facts=facts,
                        rule_objects={"recipient": user, "actor": actor},
                    )
                except Exception:  # noqa: BLE001 — never block the transition
                    logger.exception("per-use doc render failed (spec=%s)", spec.id)
                    continue
                email_service.enqueue_raw(
                    db,
                    tenant_id=tenant_id,
                    to_email=user.email,
                    subject=rendered.subject,
                    html_body=rendered.html,
                    text_body=rendered.text,
                    template_key="status.notification",
                    commit=False,
                )
                enqueued += 1
            continue

        # Engine template reference (plan 07 D10): when the spec points at a
        # template, render THROUGH the engine per recipient (brand + per-
        # recipient visibility conditions); inline subject/body otherwise.
        template = _spec_template(db, spec, tenant_id)
        if template is not None:
            for user in recipients:
                rendered = engine_render(
                    db,
                    template,
                    tenant_id,
                    {str(k): str(v) for k, v in context.items()},
                    rule_objects={"recipient": user, "actor": actor},
                )
                email_service.enqueue_raw(
                    db,
                    tenant_id=tenant_id,
                    to_email=user.email,
                    subject=rendered.subject,
                    html_body=rendered.html,
                    text_body=rendered.text,
                    template_key=template.key,
                    commit=False,
                )
                enqueued += 1
            continue

        subject = render_inline(spec.template_subject, context)
        body = render_inline(spec.template_body, context)
        for user in recipients:
            email_service.enqueue_raw(
                db,
                tenant_id=tenant_id,
                to_email=user.email,
                subject=subject,
                html_body=body.replace("\n", "<br>"),
                text_body=body,
                commit=False,
            )
            enqueued += 1
    return enqueued


def _spec_template(db: Session, spec: NotificationSpec, tenant_id: str):
    """Resolve the spec's engine template — by KEY through the two-tier read
    (a tenant fork must shadow the platform row the spec was authored
    against), tenant-scoped (polymorphic target_id rule). Render failures
    fall back to the inline body rather than blocking the transition."""
    if not spec.template_id:
        return None
    try:
        from app.models.template import Template
        from app.services.template_service import TemplateService

        row = db.get(Template, spec.template_id)
        if row is None:
            return None
        # Visibility check: the referenced row must be platform-tier or
        # belong to THIS tenant (never another tenant's fork).
        if row.tenant_id is not None and row.tenant_id != tenant_id:
            logger.warning("spec %s references foreign-tenant template — ignored", spec.id)
            return None
        return TemplateService(db).resolve_by_key(row.key, tenant_id)
    except Exception:  # noqa: BLE001 — notification must not block the transition
        logger.exception("spec template resolution failed (spec=%s)", spec.id)
        return None
