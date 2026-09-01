"""``email.send`` action (plan sprint-2/08) - render through the ONE render
pipeline (template mode) OR a bare merge-rendered email (custom mode) + enqueue
to the outbox. The workflow run boundary ends at ENQUEUE (D14): delivery/retry
is the dispatcher's job, visible in the Email log."""
import re
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.repositories.template_repository import TemplateRepository
from app.template_engine import render_email
from app.template_engine.merge import render_tokens
from app.workflow_engine.context import render_field

_TAG_RE = re.compile(r"<[^>]+>")


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


def _facts(ctx: Dict[str, Any]) -> Dict[str, str]:
    return {k: ("" if v is None else str(v)) for k, v in ctx.items()}


def email_send(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.email_service import email_service

    to_email = render_field(config.get("to"), ctx).strip()
    if not to_email:
        raise ActionError("Recipient (To) is empty after merging.")

    # Per-use template copy (plan 10 follow-up) - render the edited block doc
    # branded, taking precedence over mode.
    doc = config.get("doc")
    if doc:
        from app.template_engine import render_email_doc

        rendered = render_email_doc(
            db,
            doc_json=doc,
            subject=str(config.get("subject") or ""),
            context=str(config.get("templateContext") or "status.notification"),
            tenant_id=tenant_id,
            facts=_facts(ctx),
        )
        if not rendered.subject.strip():
            raise ActionError("Subject is empty after merging.")
        row = email_service.enqueue_raw(
            db,
            tenant_id=tenant_id,
            to_email=to_email,
            subject=rendered.subject,
            html_body=rendered.html,
            text_body=rendered.text,
            template_key="workflow.designed",
            commit=False,
        )
        return {"messageId": row.id, "status": row.status, "to": to_email}

    mode = config.get("mode") or "template"

    if mode == "custom":
        # Bare email - merge subject + body directly (no Template row). Merged
        # values are HTML-escaped in the body; the authored body HTML is kept.
        facts = _facts(ctx)
        subject = render_tokens(str(config.get("subject") or ""), facts, mode="send", escape=False).strip()
        if not subject:
            raise ActionError("Subject is empty after merging.")
        html = render_tokens(str(config.get("body") or ""), facts, mode="send", escape=True)
        text = _TAG_RE.sub("", html)
        template_key = "workflow.custom"
    else:
        template_id = config.get("templateId")
        if not template_id:
            raise ActionError("No template selected.")
        template = TemplateRepository(db).get_visible(str(template_id), tenant_id)
        if template is None:
            raise ActionError("Template not found or not accessible.")
        rendered = render_email(db, template, tenant_id, _facts(ctx))
        subject_override = render_field(config.get("subjectOverride"), ctx).strip()
        subject = subject_override or rendered.subject
        html, text = rendered.html, rendered.text
        template_key = f"workflow.{template.key}"

    row = email_service.enqueue_raw(
        db,
        tenant_id=tenant_id,
        to_email=to_email,
        subject=subject,
        html_body=html,
        text_body=text,
        template_key=template_key,
        commit=False,  # the run owns the transaction
    )
    return {"messageId": row.id, "status": row.status, "to": to_email}
