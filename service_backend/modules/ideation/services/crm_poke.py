"""Poke the tenant's CRM right after a feedback status change (owner ruling
15 Nov for CRM #2433, option c).

The CRM already pulls ``idea_status_events`` on a 15-minute safety check. This
poke only makes it pull NOW, so the dealer's WhatsApp update goes out at once:

- queued on the SAME session that writes the event rows (``_write_event``),
  the target resolved there in the same transaction, sent only after that
  session COMMITS (a rolled-back change pokes nothing);
  one poke per commit per tenant, listing every event id written in it;
- fire and forget: a background thread, a short timeout, at most ONE retry
  (transport error or 5xx only; a 4xx is the CRM saying no - never retried),
  every failure logged and swallowed - the status change never waits on, or
  fails because of, the CRM;
- target = the tenant's OWN active ``sorento`` consumer connection (the same
  base URL + ``X-API-Key`` the AutoCount sink pushes with). Never another
  tenant's, never the platform default (a poke must only reach the CRM that
  serves this tenant), never an ERROR connection. The key is never logged.
- test-idea events never poke (the feed hides them anyway).

Wire shape (path + body): provisional until the CRM lane FEEDBACK-STATUS-WA
publishes its endpoint; ``POKE_PATH`` / ``_body`` are the only places to change.
"""
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Provisional, pending the CRM lane's relay (FEEDBACK-STATUS-WA, CRM #2433).
POKE_PATH = "/api/v1/external/ideation/status-events/poke"
POKE_TIMEOUT_SECONDS = 3.0
MAX_ATTEMPTS = 2  # the call + ONE retry - never a retry storm

SORENTO_PROVIDER = "sorento"
SORENTO_CONNECTION_TYPE = "consumer"

_BUFFER = "ideation_crm_poke"

# Test seams: tests run the sender inline and capture HTTP with a MockTransport.
_transport: Optional[httpx.BaseTransport] = None


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="ideation-crm-poke", daemon=True).start()


def queue_crm_poke(db: Session, tenant_id: str, event_id: str, seq: int) -> None:
    """Remember one written status event; the poke goes out after commit.

    The tenant's target is resolved HERE, once per session, inside the same
    transaction that writes the event - so the after-commit hook does no
    database work at all (a committed session cannot run SQL, and a second
    session on the same connection would end the caller's transaction).
    Never raises: a lookup problem just means no poke."""
    try:
        buf: Dict[str, Dict[str, Any]] = db.info.setdefault(_BUFFER, {})
        entry = buf.get(tenant_id)
        if entry is None:
            entry = buf[tenant_id] = {"target": _tenant_target(db, tenant_id), "events": []}
        entry["events"].append((event_id, seq))
    except Exception:  # noqa: BLE001 - a poke never breaks the status change
        logger.exception("crm poke queue failed for tenant %s", tenant_id)


def _body(event_ids: List[str], latest_seq: int) -> Dict[str, Any]:
    return {"event_ids": event_ids, "latest_seq": latest_seq}


def _tenant_target(db: Session, tenant_id: str) -> Optional[Tuple[str, str]]:
    """``(url, api_key)`` from the tenant's OWN active, non-ERROR sorento
    consumer connection, else ``None`` (no poke)."""
    from app.models.connection import CONNECTION_STATUS_ERROR, Connection
    from app.secrets import decrypt_secret

    conn = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.provider == SORENTO_PROVIDER,
            Connection.type == SORENTO_CONNECTION_TYPE,
            Connection.is_active.is_(True),
        )
        .first()
    )
    if conn is None or conn.status == CONNECTION_STATUS_ERROR:
        return None
    base = str((conn.config_json or {}).get("baseUrl") or "").strip().rstrip("/")
    if not base or not conn.credentials_json:
        return None
    key = str(decrypt_secret(conn.credentials_json).get("apiKey") or "").strip()
    if not key:
        return None
    return f"{base}{POKE_PATH}", key


def _post(url: str, key: str, body: Dict[str, Any]) -> None:
    with httpx.Client(timeout=POKE_TIMEOUT_SECONDS, transport=_transport) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                res = client.post(url, json=body, headers={"X-API-Key": key})
            except httpx.HTTPError as exc:
                logger.warning("crm poke attempt %s failed: %s", attempt, type(exc).__name__)
                continue
            if res.status_code < 500:
                if res.status_code >= 400:
                    logger.warning("crm poke refused: HTTP %s", res.status_code)
                return
            logger.warning("crm poke attempt %s: HTTP %s", attempt, res.status_code)


def _send(url: str, key: str, body: Dict[str, Any]) -> None:
    """Runs off the request (background thread): HTTP only, no database work
    (a thread must never share the request's connection). Never raises."""
    try:
        _post(url, key, body)
    except Exception:  # noqa: BLE001 - a poke never breaks anything
        logger.exception("crm poke failed")


def _drain(committed: Session) -> None:
    """After the commit: hand each tenant's HTTP call to a background thread.
    No database work here. Never raises into the caller."""
    pending = committed.info.pop(_BUFFER, None)
    if not pending:
        return
    try:
        for entry in pending.values():
            target, events = entry["target"], entry["events"]
            if target is None or not events:
                continue
            url, key = target
            body = _body([e for e, _s in events], max(s for _e, s in events))
            _spawn(lambda u=url, k=key, b=body: _send(u, k, b))
    except Exception:  # noqa: BLE001 - after_commit must never raise into the caller
        logger.exception("crm poke dispatch failed")


def _discard(session: Session) -> None:
    session.info.pop(_BUFFER, None)


# Registered once on the Session class, like the workflow event bus.
event.listen(Session, "after_commit", _drain)
event.listen(Session, "after_rollback", _discard)
