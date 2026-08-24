"""Google Calendar through domain-wide delegation — the only ``CalendarSource``
in S0 (spine M4).

One platform-owned service account, granted domain-wide delegation by each
tenant's Workspace admin, impersonates each user in turn. No per-user OAuth, no
Google app verification, and no token to refresh in our database.

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
# the sync (spine §5.3 step 2).
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
# The connection TEST lists the domain's first users, which is the Directory
# API, not Calendar — a tenant must grant this second scope for the Test button
# to answer (AC-S0-4).
DIRECTORY_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user.readonly"]

# What a Google client raises when a sync token has expired.
_GONE = 410


def _service_account_credentials(service_account_json: str, scopes: List[str], subject: str):
    """Delegated credentials for ONE impersonated user. Lazy Google import."""
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
        return creds.with_subject(subject)
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
    """The domain's first ``limit`` user emails — what the Test button proves.

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
    """``CalendarSource`` over Google Calendar with domain-wide delegation."""

    def __init__(self, service_account_json: str):
        self._service_account_json = service_account_json

    def _service(self, user_email: str):
        creds = _service_account_credentials(
            self._service_account_json, CALENDAR_SCOPES, user_email
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
            "calendarId": "primary",
            "singleEvents": True,
            "maxResults": 250,
        }
        if sync_token:
            params["syncToken"] = sync_token
        else:
            # Google rejects orderBy/timeMin alongside a syncToken, which is why
            # the window is only ever sent on a full read.
            params["timeMin"] = _rfc3339(time_min)
            params["timeMax"] = _rfc3339(time_max)
            params["orderBy"] = "startTime"

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
