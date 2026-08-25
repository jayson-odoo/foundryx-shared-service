"""Meetings connection providers (S0 plan §2, AC-S0-4 / AC-S0-5).

Both register into the CORE provider registry (``app/integrations``), so they are
configured through the same ``/settings/integrations`` Resource shell as SMTP and
S3 — no bespoke connection UI, and secrets ride the existing Fernet path.

They are two SEPARATE connection types on purpose. ``uq_connection_tenant_type``
allows one active connection per type, and a tenant needs BOTH of these at once
— so a single shared type would make the second one unsavable, the trap the
``payment``/``erp`` carve-outs exist for.
"""
import json
import re
from typing import Any, Dict, List, Optional

from app.integrations.base import TestResult

from .calendar.base import CalendarSourceError
from .calendar.google_dwd import (
    GoogleDwdCalendarSource,
    impersonation_enabled,
    list_directory_users,
    probe_calendar,
    service_account_email,
)
from .services.optin import opted_in_calendars

GOOGLE_DWD_PROVIDER = "google_dwd"
GOOGLE_DWD_TYPE = "calendar"
MEET_BOT_PROVIDER = "meet_bot"
MEET_BOT_TYPE = "meeting_bot"

# How many calendars the shared-mode Test names before it stops listing.
_PROBE_LIMIT = 10

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GoogleDwdProvider:
    """Google Calendar, in either of the two access modes (spine M4).

    ``impersonate`` off (the default) is SHARED-CALENDAR mode: the service
    account reads calendars that users shared with its own address. On is
    domain-wide delegation, which needs a Workspace admin to grant it.
    """

    provider = GOOGLE_DWD_PROVIDER
    type = GOOGLE_DWD_TYPE
    title = "Google Calendar"
    description = (
        "Read calendars with one service account: either shared with its address "
        "by each user, or through domain-wide delegation."
    )
    icon = "calendar"
    test_label = "Test connection"
    # No targeted test: reading a calendar is the connection check.
    test_target = None
    # Shared mode probes the opted-in users' OWN calendars, so this test needs
    # the tenant's rows — core hands over ``db`` + ``tenant_id`` when a provider
    # declares this (the only provider that does).
    test_needs_context = True

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                # A select, not a checkbox: the shared connection form stores
                # every non-secret field as a string, and two named modes read
                # better on the page than a bare switch.
                "key": "impersonate",
                "label": "Access",
                "type": "select",
                "required": False,
                "defaultValue": "off",
                "options": [
                    {"value": "off", "label": "Calendars shared with the service account"},
                    {"value": "on", "label": "Domain-wide delegation"},
                ],
            },
            {
                "key": "impersonateEmail",
                "label": "Admin email",
                # Only domain-wide delegation impersonates anyone, so this is not
                # required at the form level; ``test`` rejects a missing value in
                # the mode that actually needs it.
                "type": "text",
                "required": False,
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
        *,
        db: Any = None,
        tenant_id: Optional[str] = None,
    ) -> TestResult:
        """Prove the mode this connection is actually in.

        A catch-all "connection failed" is banned here: the operator has to know
        whether to fix the key, the impersonated admin, the delegation grant or a
        calendar share (AC-S0-4)."""
        key = str(credentials.get("serviceAccountJson") or "")
        if not key:
            return TestResult(ok=False, message="Add the service-account key first.")
        try:
            json.loads(key)
        except (TypeError, ValueError):
            return TestResult(
                ok=False, message="The service-account key is not valid JSON."
            )
        if impersonation_enabled(config):
            return self._test_delegated(key, config)
        return self._test_shared(key, db, tenant_id)

    # ── domain-wide delegation ───────────────────────────────────────────────

    def _test_delegated(self, key: str, config: Dict[str, Any]) -> TestResult:
        admin = str(config.get("impersonateEmail") or "").strip()
        if not _EMAIL_RE.match(admin):
            return TestResult(ok=False, message="Add the admin email to impersonate.")
        try:
            emails = list_directory_users(
                service_account_json=key, impersonate_email=admin, limit=5
            )
        except CalendarSourceError as exc:
            return TestResult(ok=False, message=str(exc))
        except Exception as exc:  # noqa: BLE001 — never a raw traceback
            return TestResult(ok=False, message=str(exc))
        if not emails:
            return TestResult(
                ok=False,
                message="The domain returned no users for this admin.",
            )
        return TestResult(ok=True, message="Reading " + ", ".join(emails))

    # ── shared calendars ─────────────────────────────────────────────────────

    def _test_shared(self, key: str, db: Any, tenant_id: Optional[str]) -> TestResult:
        """Read every opted-in user's calendar and report which ones answer.

        NOT ``calendarList``: a calendar shared with a service account does not
        appear in that account's list at all (verified against a real key — it
        came back empty while ``events.list`` on the same address worked), so
        listing would report "no calendars" for a correctly shared one."""
        address = service_account_email(key) or "the service account"
        calendars = opted_in_calendars(db, tenant_id)
        if not calendars:
            return TestResult(
                ok=False,
                message=(
                    f"Nobody has switched their meetings on yet. Share a calendar "
                    f"with {address}, switch Record my meetings on, then test again."
                ),
            )
        readable: List[str] = []
        failures: List[str] = []
        for calendar_id in calendars[:_PROBE_LIMIT]:
            try:
                probe_calendar(service_account_json=key, calendar_id=calendar_id)
            except CalendarSourceError as exc:
                failures.append(f"{calendar_id}: {exc}")
            except Exception as exc:  # noqa: BLE001 — never a raw traceback
                failures.append(f"{calendar_id}: {exc}")
            else:
                readable.append(calendar_id)
        if failures:
            # PARTIAL success is still a failure: a calendar nobody shared means
            # that user's meetings are silently never captured.
            return TestResult(
                ok=False,
                message=(
                    f"{address} cannot read " + "; ".join(failures)
                    + (f". Reading {', '.join(readable)}." if readable else ".")
                ),
            )
        return TestResult(ok=True, message="Reading " + ", ".join(readable))


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
    return GoogleDwdCalendarSource(key, impersonate=impersonation_enabled(config))
