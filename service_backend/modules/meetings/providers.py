"""Meetings connection providers (S0 plan §2, AC-S0-4 / AC-S0-5).

Both register into the CORE provider registry (``app/integrations``), so they are
configured through the same ``/settings/integrations`` Resource shell as SMTP and
S3 - no bespoke connection UI, and secrets ride the existing Fernet path.

They are two SEPARATE connection types on purpose. ``uq_connection_tenant_type``
allows one active connection per type, and a tenant needs BOTH of these at once
- so a single shared type would make the second one unsavable, the trap the
``payment``/``erp`` carve-outs exist for.
"""
import json
import re
from typing import Any, Dict, List, Optional

from app.integrations.base import TestResult

from .calendar.base import CalendarSourceError
from .calendar.google_dwd import GoogleDwdCalendarSource, list_directory_users

GOOGLE_DWD_PROVIDER = "google_dwd"
GOOGLE_DWD_TYPE = "calendar"
MEET_BOT_PROVIDER = "meet_bot"
MEET_BOT_TYPE = "meeting_bot"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GoogleDwdProvider:
    """Google Calendar via domain-wide delegation (spine M4)."""

    provider = GOOGLE_DWD_PROVIDER
    type = GOOGLE_DWD_TYPE
    title = "Google Calendar (domain-wide delegation)"
    description = (
        "Read every user's calendar with one service account the Workspace admin "
        "authorises once. No per-user sign-in."
    )
    icon = "calendar"
    test_label = "Test connection"
    # No targeted test: reading a calendar is the connection check.
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "impersonateEmail",
                "label": "Admin email",
                "type": "text",
                "required": True,
                "placeholder": "admin@yourdomain.com",
            },
            {
                "key": "serviceAccountJson",
                "label": "Service account key",
                "type": "text",
                "required": True,
                "secret": True,
                "placeholder": '{"type": "service_account", …}',
            },
        ]

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
    ) -> TestResult:
        """List the domain's first five users, or hand back Google's own error.

        A catch-all "connection failed" is banned here: the operator has to know
        whether to fix the key, the impersonated admin, or the delegation grant
        (AC-S0-4)."""
        key = str(credentials.get("serviceAccountJson") or "")
        admin = str(config.get("impersonateEmail") or "").strip()
        if not key:
            return TestResult(ok=False, message="Add the service-account key first.")
        if not _EMAIL_RE.match(admin):
            return TestResult(ok=False, message="Add the admin email to impersonate.")
        try:
            json.loads(key)
        except (TypeError, ValueError):
            return TestResult(
                ok=False, message="The service-account key is not valid JSON."
            )
        try:
            emails = list_directory_users(
                service_account_json=key, impersonate_email=admin, limit=5
            )
        except CalendarSourceError as exc:
            return TestResult(ok=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - never a raw traceback
            return TestResult(ok=False, message=str(exc))
        if not emails:
            return TestResult(
                ok=False,
                message="The domain returned no users for this admin.",
            )
        return TestResult(ok=True, message="Reading " + ", ".join(emails))


class MeetBotProvider:
    """The tenant's notetaker Workspace account (spine M5).

    S0 stores it; S2's bot is what signs in with it. It offers NO test at all
    (``test_label`` is empty, which is how a provider declares that): verifying
    this account means a real interactive sign-in, and a cheaper check that
    answered ok would stamp the connection ACTIVE and show the operator
    "Connected" for an account nobody has signed into (AC-S0-5).
    """

    provider = MEET_BOT_PROVIDER
    type = MEET_BOT_TYPE
    title = "Meeting notetaker account"
    description = (
        "The account the notetaker joins meetings as. Create it inside your own "
        "domain and exempt it from 2-step verification."
    )
    icon = "bot"
    # Empty = this provider offers no test; the connection stays UNVERIFIED
    # until the bot really signs in, in S2.
    test_label = ""
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "email",
                "label": "Notetaker email",
                "type": "text",
                "required": True,
                "placeholder": "notetaker@yourdomain.com",
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "required": True,
                "secret": True,
            },
            {
                "key": "displayNameOverride",
                "label": "Display name",
                "type": "text",
                "required": False,
                "advanced": True,
                "placeholder": "Notetaker",
            },
        ]


def calendar_source_from_connection(
    config: Dict[str, Any], credentials: Dict[str, Any]
) -> GoogleDwdCalendarSource:
    """Build the sync's ``CalendarSource`` from a stored ``google_dwd`` row.

    Credentials arrive already DECRYPTED (``app/secrets.decrypt_secret``); this
    module never handles ciphertext or a module-local key."""
    key = str(credentials.get("serviceAccountJson") or "")
    if not key:
        raise CalendarSourceError("The Google Calendar connection has no key stored.")
    return GoogleDwdCalendarSource(key)
