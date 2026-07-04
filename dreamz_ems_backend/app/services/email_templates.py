"""Email template rendering (plan 09 D9) — Jinja2, Dreamz-branded base layout
+ per-key children with plain-text siblings. User-editable templates /
per-tenant branding = BL-038 (ties BL-024 template engine).
"""
from pathlib import Path
from typing import Any, Dict, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

SUBJECTS: Dict[str, str] = {
    "invite": "You're invited to Dreamz EMS",
    "password_reset": "Reset your Dreamz EMS password",
    "verification": "Verify your email for Dreamz EMS",
    "test": "Dreamz EMS — SMTP test email",
    # Change-email ceremony (plan sprint-2/04).
    "email_change_approve": "Approve the email change on your account",
    "email_change_verify": "Confirm your new email address",
    "email_change_notice": "The email on your account was changed",
}


def render_email(template_key: str, context: Dict[str, Any]) -> Tuple[str, str, str]:
    """Render `(subject, html_body, text_body)` for a template key."""
    if template_key not in SUBJECTS:
        raise ValueError(f"Unknown email template '{template_key}'.")
    html = _env.get_template(f"{template_key}.html").render(**context)
    text = _env.get_template(f"{template_key}.txt").render(**context)
    return SUBJECTS[template_key], html, text
