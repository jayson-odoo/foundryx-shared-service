"""Generic SMTP provider (plan 09 D4) — covers any SMTP endpoint (Gmail, SES,
Resend, Mailgun, self-hosted). One adapter, any provider; API-native adapters
(Resend REST / SES SDK) are BL-046.

`test()` without a target = connection check: connect + (when credentials are
set) authenticate, then QUIT — no mail sent. With a target = send a real test
email. `send()` is the dispatcher's transport.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, List, Optional

from app.config import settings
from app.integrations.base import TestResult


def _smtp_connect(config: Dict[str, Any], credentials: Dict[str, Any]) -> smtplib.SMTP:
    """Open + authenticate an SMTP session per the connection config."""
    host = str(config.get("host", ""))
    port = int(config.get("port", 587))
    security = str(config.get("security", "starttls"))
    timeout = settings.email_send_timeout_seconds

    if security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            host, port, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
        if security == "starttls":
            client.starttls(context=ssl.create_default_context())

    username = str(config.get("username", ""))
    password = str(credentials.get("password", ""))
    if username and password:
        client.login(username, password)
    return client


def smtp_send(
    config: Dict[str, Any],
    credentials: Dict[str, Any],
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send one email over the connection. Raises on any transport failure."""
    msg = EmailMessage()
    from_email = str(config.get("fromEmail") or config.get("username", ""))
    from_name = str(config.get("fromName", ""))
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    client = _smtp_connect(config, credentials)
    try:
        client.send_message(msg)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001 — best-effort QUIT
            pass


class SmtpProvider:
    provider = "smtp"
    type = "email"
    title = "Email (SMTP)"
    description = (
        "Send invites, password resets and verifications from your own mail server. "
        "Works with any SMTP provider — Gmail, SES, Resend, Mailgun or self-hosted."
    )
    icon = "mail"
    test_label = "Send test email"
    test_target = {"label": "Send a test email to", "placeholder": "you@yourcompany.com"}

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "host", "label": "SMTP host", "type": "text", "required": True,
             "placeholder": "smtp.yourcompany.com"},
            {"key": "port", "label": "Port", "type": "number", "required": True,
             "defaultValue": "587"},
            {"key": "security", "label": "Security", "type": "select", "required": True,
             "defaultValue": "starttls",
             "options": [
                 {"value": "starttls", "label": "STARTTLS"},
                 {"value": "ssl", "label": "SSL/TLS"},
                 {"value": "none", "label": "None (not recommended)"},
             ]},
            {"key": "username", "label": "Username", "type": "text", "required": False,
             "placeholder": "mailer@yourcompany.com"},
            {"key": "password", "label": "Password", "type": "password", "required": False,
             "secret": True},
            {"key": "fromEmail", "label": "From email", "type": "text", "required": True,
             "placeholder": "no-reply@yourcompany.com"},
            {"key": "fromName", "label": "From name", "type": "text", "required": False,
             "placeholder": "Your Company"},
        ]

    def send(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> None:
        """Dispatcher transport — raises on failure (drives retry/fallback)."""
        smtp_send(config, credentials, to_email, subject, html_body, text_body)

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        try:
            if target:
                from app.services.email_templates import render_email

                subject, html, text = render_email(
                    "test", {"product": "FoundryX EMS"}
                )
                smtp_send(config, credentials, target, subject, html, text)
                return TestResult(ok=True, message=f"Test email sent to {target}.")
            client = _smtp_connect(config, credentials)
            try:
                client.noop()
            finally:
                try:
                    client.quit()
                except Exception:  # noqa: BLE001
                    pass
            return TestResult(ok=True, message="Connection verified.")
        except smtplib.SMTPAuthenticationError as e:
            detail = e.smtp_error.decode() if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
            return TestResult(ok=False, message=f"SMTP authentication failed ({e.smtp_code} {detail}).")
        except (smtplib.SMTPException, OSError) as e:
            host = config.get("host", "?")
            port = config.get("port", "?")
            return TestResult(ok=False, message=f"Could not connect to {host}:{port} ({e}).")
