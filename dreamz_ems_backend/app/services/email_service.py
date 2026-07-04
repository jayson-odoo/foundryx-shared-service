"""Email delivery (plan 09 §5) — outbox-backed.

`EmailService` renders the Jinja2 template and ENQUEUES an `email_outbox` row;
the dispatcher (email_dispatcher.py) delivers it with per-connection rate
limiting, retry/backoff and tenant→platform fallback (BL-006 closed).

Dev fallback preserved: when NO smtp connection resolves for the recipient's
tenant (nor the platform default), the link is console-logged immediately and
the row is marked sent — local dev + tests need zero mail infra.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.email_outbox import OUTBOX_PENDING, OUTBOX_SENT, EmailOutbox
from app.repositories.connection_repository import ConnectionRepository
from app.services.email_templates import render_email

logger = logging.getLogger("dreamz.email")

EMAIL_PROVIDER = "smtp"


def _now() -> datetime:
    # House convention since plan sprint-2/05: AWARE UTC everywhere (columns are timestamptz).
    return datetime.now(timezone.utc)


# Legacy Jinja key → (engine template key, link-fact name) — plan 07 D7.
_ENGINE_KEYS: Dict[str, tuple] = {
    "invite": ("auth.invite", "inviteLink"),
    "password_reset": ("auth.password_reset", "resetLink"),
    "verification": ("auth.verification", "verifyLink"),
    "email_change_approve": ("account.email_change_approve", "approveLink"),
    "email_change_verify": ("account.email_change_verify", "verifyLink"),
    "email_change_notice": ("account.email_change_notice", None),
}


class OutboxEmailService:
    """Renders + enqueues. Call sites pass the recipient's tenant (plan 09 D6)."""

    def _render_via_engine(
        self,
        db: Session,
        tenant_id: str,
        to_email: str,
        template_key: str,
        context: Dict[str, Any],
    ):
        """Engine render (plan 07 D7) — None if no template resolves
        (fresh/unseeded DB falls back to the legacy Jinja file)."""
        mapping = _ENGINE_KEYS.get(template_key)
        if mapping is None:
            return None
        engine_key, link_fact = mapping
        try:
            from app.config import settings
            from app.models.tenant import Tenant
            from app.models.user import User
            from app.services.template_service import TemplateService
            from app.template_engine import render_email as engine_render

            template = TemplateService(db).resolve_by_key(engine_key, tenant_id)
            if template is None:
                return None

            recipient = (
                db.query(User)
                .filter(User.tenant_id == tenant_id, User.email == to_email)
                .first()
            )
            tenant = db.get(Tenant, tenant_id)
            facts: Dict[str, str] = {
                "tenant.name": tenant.name if tenant else "",
                "recipient.email": to_email,
                "recipient.name": (recipient.name or to_email) if recipient else to_email,
                "recipient.firstName": (
                    ((recipient.name or "").split(" ")[0] or to_email)
                    if recipient
                    else to_email
                ),
                "expiresInMinutes": str(settings.reset_token_ttl_minutes),
                "expiresInDays": str(settings.invite_token_ttl_minutes // (60 * 24)),
            }
            if link_fact and "link" in context:
                facts[link_fact] = context["link"]
            if "new_email_masked" in context:
                facts["newEmail"] = context["new_email_masked"]
            if "old_email" in context:
                facts["oldEmail"] = context["old_email"]
            if "new_email" in context:
                facts["newEmail"] = context["new_email"]

            rendered = engine_render(
                db,
                template,
                tenant_id,
                facts,
                rule_objects={"recipient": recipient} if recipient else {},
            )
            return rendered.subject, rendered.html, rendered.text, engine_key
        except Exception:  # noqa: BLE001 — a broken template must NEVER block auth mail
            logger.exception(
                "engine render failed for %s — falling back to legacy template", template_key
            )
            return None

    def _enqueue(
        self,
        db: Session,
        tenant_id: str,
        to_email: str,
        template_key: str,
        context: Dict[str, Any],
    ) -> EmailOutbox:
        engine = self._render_via_engine(db, tenant_id, to_email, template_key, context)
        if engine is not None:
            subject, html, text, template_key = engine
        else:
            subject, html, text = render_email(template_key, context)
        connection = ConnectionRepository(db).resolve_for_send(tenant_id, EMAIL_PROVIDER)

        row = EmailOutbox(
            tenant_id=tenant_id,
            to_email=to_email,
            subject=subject,
            html_body=html,
            text_body=text,
            template_key=template_key,
            next_attempt_at=_now(),
        )
        if connection is None:
            # Dev fallback — identical DX to the old DevLog adapter.
            link = context.get("link", "")
            logger.info("[email:%s] to=%s link=%s", template_key, to_email, link)
            print(f"[email:{template_key}] to={to_email} link={link}")
            row.status = OUTBOX_SENT
            row.sent_at = _now()
        else:
            row.status = OUTBOX_PENDING

        db.add(row)
        # Commit here — enqueue is the terminal action of these flows and the
        # invite-token repo has already committed by this point; a flush-only
        # row would silently roll back when the request session closes.
        db.commit()
        return row

    def enqueue_raw(
        self,
        db: Session,
        tenant_id: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        template_key: str = "status_notification",
        commit: bool = True,
    ) -> EmailOutbox:
        """Enqueue an already-rendered email (status-engine notify-on-transition,
        sprint-2/01 — inline merge-field templates render before this point;
        the Template engine BL-024 swaps that renderer later). Same outbox
        semantics as ``_enqueue``; ``commit=False`` lets the caller own the
        transaction (the status machine commits transition + emails atomically).
        """
        connection = ConnectionRepository(db).resolve_for_send(tenant_id, EMAIL_PROVIDER)
        row = EmailOutbox(
            tenant_id=tenant_id,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            template_key=template_key,
            next_attempt_at=_now(),
        )
        if connection is None:
            logger.info("[email:%s] to=%s subject=%s", template_key, to_email, subject)
            print(f"[email:{template_key}] to={to_email} subject={subject}")
            row.status = OUTBOX_SENT
            row.sent_at = _now()
        else:
            row.status = OUTBOX_PENDING
        db.add(row)
        if commit:
            db.commit()
        else:
            db.flush()
        return row

    def send_invite(self, db: Session, to_email: str, link: str, tenant_id: str) -> None:
        self._enqueue(db, tenant_id, to_email, "invite", {"link": link})

    def send_password_reset(self, db: Session, to_email: str, link: str, tenant_id: str) -> None:
        self._enqueue(db, tenant_id, to_email, "password_reset", {"link": link})

    def send_verification(self, db: Session, to_email: str, link: str, tenant_id: str) -> None:
        self._enqueue(db, tenant_id, to_email, "verification", {"link": link})

    # ---- Change-email ceremony (plan sprint-2/04) ----

    def send_email_change_approve(
        self, db: Session, to_email: str, link: str, tenant_id: str, *, new_email_masked: str
    ) -> None:
        """OLD-side approve mail — identifies the request without disclosing
        the full target address."""
        self._enqueue(
            db,
            tenant_id,
            to_email,
            "email_change_approve",
            {"link": link, "new_email_masked": new_email_masked},
        )

    def send_email_change_verify(
        self, db: Session, to_email: str, link: str, tenant_id: str
    ) -> None:
        self._enqueue(db, tenant_id, to_email, "email_change_verify", {"link": link})

    def send_email_change_notice(
        self, db: Session, to_email: str, tenant_id: str, *, old_email: str, new_email: str
    ) -> None:
        """Plain notification (no link) — sent to the previous address on
        ceremony completion, and to BOTH addresses on an admin instant change."""
        self._enqueue(
            db,
            tenant_id,
            to_email,
            "email_change_notice",
            {"old_email": old_email, "new_email": new_email},
        )

    # ---- Profile Portal (EMS, sprint-4/06 slice 0a) ----
    # Plain (non-engine) renders via enqueue_raw — the portal-auth contexts are
    # out of scope for 0a; full Template-engine adoption is a later slice.

    def send_profile_otp(self, db: Session, to_email: str, code: str, tenant_id: str) -> None:
        subject = "Your sign-in code"
        text = (
            f"Your one-time sign-in code is: {code}\n\n"
            "It expires shortly. If you did not request it, ignore this email."
        )
        html = (
            f"<p>Your one-time sign-in code is:</p>"
            f"<p style=\"font-size:24px;font-weight:bold;letter-spacing:3px\">{code}</p>"
            "<p>It expires shortly. If you did not request it, ignore this email.</p>"
        )
        self.enqueue_raw(
            db, tenant_id, to_email, subject, html, text, template_key="portal.otp"
        )

    def send_profile_set_password(
        self, db: Session, to_email: str, link: str, tenant_id: str
    ) -> None:
        subject = "Set your portal password"
        text = f"Set your portal password using this link:\n{link}\n\nThe link can be used once."
        html = (
            "<p>Set your portal password using this link:</p>"
            f"<p><a href=\"{link}\">{link}</a></p>"
            "<p>The link can be used once.</p>"
        )
        self.enqueue_raw(
            db, tenant_id, to_email, subject, html, text, template_key="portal.set_password"
        )


email_service = OutboxEmailService()
