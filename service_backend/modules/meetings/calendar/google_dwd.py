"""Google Calendar through one service account — the only ``CalendarSource``.

TWO modes, one adapter, one flag (``impersonate`` on the connection config):

* **Domain-wide delegation** (``impersonate`` on, spine M4). The Workspace admin
  authorises the service account once; it then impersonates each user in turn and
  reads their ``primary`` calendar. Needs Workspace admin access to set up.
* **Shared calendar** (``impersonate`` off, the DEFAULT). The service account uses
  its OWN credentials and reads ``calendarId=<the user's calendar address>``,
  which works as soon as that user shares their calendar with the service-account
  email at "See all event details". No Workspace admin, no delegation grant - the
  mode a tenant whose admin will not grant DWD can actually use.

The Google client is imported LAZILY, so this module imports cleanly (and the
whole test suite runs) on a machine with no ``google-api-python-client``
installed. The sync's tests drive a scripted ``CalendarSource`` instead of this
class, which is why nothing here needs an injection seam.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import (
    CalendarSourceError,
    RawEvent,
    SyncPage,
    SyncTokenInvalid,
    find_conference_url,
)

# Read the user's calendar; that is the whole delegation the tenant grants for
# the sync (spine §5.3 step 2), and also the only scope shared mode ever needs.
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
# The connection TEST lists the domain's first users in DWD mode, which is the
# Directory API, not Calendar - a tenant must grant this second scope for that
# button to answer (AC-S0-4). Shared mode never touches it.
DIRECTORY_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user.readonly"]

# What a Google client raises when a sync token has expired.
_GONE = 410


def impersonation_enabled(config: Dict[str, Any]) -> bool:
    """Is this connection in domain-wide-delegation mode?

    The wire value is a STRING (the shared connection form stores every
    non-secret field as one), so "off", "" and a missing key all mean shared
    mode - the default, because it is the mode that needs no Workspace admin."""
    raw = str((config or {}).get("impersonate") or "").strip().lower()
    return raw in ("1", "on", "true", "yes")


def service_account_email(service_account_json: str) -> Optional[str]:
    """The ``client_email`` out of a stored key - the address a user has to
    share their calendar WITH. Never the key itself, never the private key."""
    try:
        info = json.loads(service_account_json or "")
    except (TypeError, ValueError):
        return None
    email = info.get("client_email") if isinstance(info, dict) else None
    return str(email) if email else None


def _service_account_credentials(
    service_account_json: str, scopes: List[str], subject: Optional[str]
):
    """Service-account credentials, delegated to ``subject`` when one is given.

    ``subject=None`` is shared mode: the service account acts as ITSELF, which is
    what makes a calendar shared with it readable without any delegation."""
    try:
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:  # pragma: no cover — dependency guard
        raise CalendarSourceError(
            "The Google API client is not installed on this server "
            "(pip install google-api-python-client google-auth)."
        ) from exc
    try:
        info = json.loads(service_account_json)
    except (TypeError, ValueError) as exc:
        raise CalendarSourceError("The service-account key is not valid JSON.") from exc
    try:
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        return creds.with_subject(subject) if subject else creds
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim to the operator
        raise CalendarSourceError(str(exc)) from exc


def _build(api: str, version: str, credentials):
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:  # pragma: no cover — dependency guard
        raise CalendarSourceError(
            "The Google API client is not installed on this server "
            "(pip install google-api-python-client google-auth)."
        ) from exc
    return build(api, version, credentials=credentials, cache_discovery=False)


def _status_of(exc: Exception) -> Optional[int]:
    """The HTTP status a googleapiclient error carries, if any."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def list_directory_users(
    *, service_account_json: str, impersonate_email: str, limit: int = 5
) -> List[str]:
    """The domain's first ``limit`` user emails — what the DWD Test proves.

    Raises ``CalendarSourceError`` carrying Google's own message, because
    "connection failed" tells the operator nothing about whether to fix the key,
    the impersonated admin or the delegation grant (AC-S0-4)."""
    creds = _service_account_credentials(
        service_account_json, DIRECTORY_SCOPES, impersonate_email
    )
    try:
        service = _build("admin", "directory_v1", creds)
        response = (
            service.users()
            .list(customer="my_customer", maxResults=limit, orderBy="email")
            .execute()
        )
    except CalendarSourceError:
        raise
    except (TypeError, ValueError) as exc:
        raise CalendarSourceError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — Google's message, verbatim
        raise CalendarSourceError(_google_message(exc)) from exc
    return [u.get("primaryEmail", "") for u in (response.get("users") or [])][:limit]


def probe_calendar(*, service_account_json: str, calendar_id: str) -> None:
    """Can the service account, AS ITSELF, read ``calendar_id``? Raises with
    Google's own message when it cannot.

    A calendar shared with a service account does NOT show up in that account's
    ``calendarList`` (verified against a real key: the list comes back empty),
    so listing is worthless as a check - reading the calendar is the only proof
    that the share was actually granted."""
    creds = _service_account_credentials(service_account_json, CALENDAR_SCOPES, None)
    try:
        service = _build("calendar", "v3", creds)
        service.events().list(calendarId=calendar_id, maxResults=1).execute()
    except CalendarSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — Google's message, verbatim
        raise CalendarSourceError(_google_message(exc)) from exc


def _google_message(exc: Exception) -> str:
    """Google's own wording, unwrapped from the client's error envelope."""
    content = getattr(exc, "content", None)
    if content:
        try:
            body = json.loads(content)
            message = body.get("error", {}).get("message")
            if message:
                return message
        except (TypeError, ValueError):
            pass
    return str(exc)


class GoogleDwdCalendarSource:
    """``CalendarSource`` over Google Calendar, in either mode.

    ``user_email`` is the CALENDAR ADDRESS to read (``user_opt_ins.calendar_email``
    when the user set one, else their login email). In DWD mode it is also the
    subject the service account impersonates.
    """

    def __init__(self, service_account_json: str, *, impersonate: bool = False):
        self._service_account_json = service_account_json
        self._impersonate = impersonate

    def _service(self, user_email: str):
        subject = user_email if self._impersonate else None
        creds = _service_account_credentials(
            self._service_account_json, CALENDAR_SCOPES, subject
        )
        return _build("calendar", "v3", creds)

    def list_events(
        self,
        *,
        user_email: str,
        sync_token: Optional[str] = None,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> SyncPage:
        service = self._service(user_email)
        params: Dict[str, Any] = {
            # Impersonating the user, their own calendar IS "primary"; acting as
            # ourselves we have to name the calendar that was shared with us.
            "calendarId": "primary" if self._impersonate else user_email,
            "singleEvents": True,
            "maxResults": 250,
        }
        if sync_token:
            params["syncToken"] = sync_token
        else:
            # Google rejects timeMin/timeMax alongside a syncToken, which is why
            # the window is only ever sent on a full read.
            #
            # ``orderBy`` is deliberately ABSENT. Google drops ``nextSyncToken``
            # from any response that carries an orderBy (verified against a real
            # calendar: the same request answers with a token without it and
            # without one with it), so asking for sorted events costs us the
            # token and every later read would be a full one. Nothing downstream
            # cares about the order events arrive in.
            params["timeMin"] = _rfc3339(time_min)
            params["timeMax"] = _rfc3339(time_max)

        events: List[RawEvent] = []
        next_sync_token: Optional[str] = None
        page_token: Optional[str] = None
        while True:
            try:
                response = (
                    service.events().list(**params, pageToken=page_token).execute()
                    if page_token
                    else service.events().list(**params).execute()
                )
            except Exception as exc:  # noqa: BLE001
                if _status_of(exc) == _GONE:
                    raise SyncTokenInvalid(_google_message(exc)) from exc
                raise CalendarSourceError(_google_message(exc)) from exc
            events.extend(parse_event(item) for item in response.get("items", []))
            next_sync_token = response.get("nextSyncToken") or next_sync_token
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return SyncPage(events=events, next_sync_token=next_sync_token)


def _rfc3339(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_event(item: Dict[str, Any]) -> RawEvent:
    """One Google event payload → a provider-neutral ``RawEvent``.

    The conference link comes from ``conferenceData`` when Google attached a Meet
    itself, and otherwise from a regex over ``hangoutLink`` / ``location`` /
    ``description`` — which is where a Zoom or Teams invite actually lives (S0
    plan §3)."""
    conference_url = _conference_from_data(item.get("conferenceData")) or find_conference_url(
        item.get("hangoutLink"), item.get("location"), item.get("description")
    )
    organiser = (item.get("organizer") or {}).get("email")
    attendees = [
        {
            "email": a.get("email"),
            "displayName": a.get("displayName"),
            "responseStatus": a.get("responseStatus"),
        }
        for a in (item.get("attendees") or [])
        if a.get("email")
    ]
    return RawEvent(
        external_id=item.get("id", ""),
        starts_at=_parse_dt(item.get("start")),
        ends_at=_parse_dt(item.get("end")),
        title=item.get("summary"),
        organiser_email=organiser,
        attendees=attendees,
        conference_url=conference_url,
        cancelled=item.get("status") == "cancelled",
    )


def _conference_from_data(conference_data: Optional[Dict[str, Any]]) -> Optional[str]:
    for entry in (conference_data or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def _parse_dt(slot: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """Google's ``{"dateTime": …}`` (or all-day ``{"date": …}``) → aware UTC."""
    if not slot:
        return None
    raw = slot.get("dateTime") or slot.get("date")
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
