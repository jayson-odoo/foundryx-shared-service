"""Google sign-in on the hosted wizard (plan 68, G-D1..G-D9).

The Google twin of the Facebook automatic path, on top of the guided receiver
(card 68a): sign in with Google -> pick the Google Ads account -> tick lead
forms -> we write OUR inbound URL + the source's key into each ticked form.

- The login rides the same connect session and scoped wizard token as
  Facebook (``WizardPrincipal``); the Google tokens are Fernet on the session
  row (``google_encrypted``) and never cross the wire (G-D3).
- Every account / form id from the client is checked against what Google
  lists for the signed-in person (never trusted).
- Connect creates the source with the ONE create function
  (``google_source_service.create_guided_source``); a session already bound
  to a Google source reuses it and its key, so "Try again" on one refused
  form never breaks the forms that already work (G-D5).
- Off unless ``LEAD_CAPTURE_GOOGLE_SIGNIN`` is on; without
  ``GOOGLE_ADS_CLIENT_ID`` it is simulated (G-D7).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.secrets import decrypt_secret, encrypt_secret

from .. import google_ads
from ..google_ads import GoogleAdsClient, GoogleAdsError
from ..models import PLATFORM_GOOGLE, SOURCE_DISCONNECTED, LcSource
from . import google_source_service, source_service
from .connect_session_service import LOGIN_TTL, SessionError, WizardPrincipal

logger = logging.getLogger(__name__)

MAX_FORMS = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def login_config() -> Dict[str, Any]:
    simulated = not google_ads.configured()
    return {
        "available": bool(settings.lead_capture_google_signin),
        "simulated": simulated,
        "clientId": settings.google_ads_client_id or None,
        "scopes": list(google_ads.LOGIN_SCOPES),
    }


def _require_available() -> None:
    if not settings.lead_capture_google_signin:
        raise SessionError(409, "channel_unavailable", "Google sign-in is not available right now.")


def wizard_login(
    db: Session, principal: WizardPrincipal, code: str, redirect_uri: Optional[str], *, client: Optional[GoogleAdsClient] = None
) -> List[Dict[str, str]]:
    """Exchange ``code``, check the Google Ads permission, store the tokens
    (Fernet) on the session and return the accounts the person can reach."""
    _require_available()
    code = (code or "").strip()
    if not code or len(code) > 2048:
        raise SessionError(422, "invalid_code", "The Google sign-in did not finish. Try again.")
    api = client or GoogleAdsClient()
    try:
        creds = api.exchange_code(code, redirect_uri)
    except GoogleAdsError:
        logger.info("lead capture google code exchange refused")
        raise SessionError(400, "LOGIN_FAILED", "Google did not finish the sign-in. Try again.") from None
    if google_ads.ADS_SCOPE not in creds["scopes"]:
        raise SessionError(
            400,
            "PERMISSION_DECLINED",
            "Google did not give permission to manage your Google Ads lead forms. Leave every box ticked on the Google screen.",
        )
    dev = bool(creds["dev"])
    accounts = _accounts(api, creds["accessToken"], dev)
    row = principal.session
    row.google_encrypted = encrypt_secret(
        {
            "accessToken": creds["accessToken"],
            "refreshToken": creds["refreshToken"],
            "email": api.email(creds["accessToken"], dev=dev),
            "dev": dev,
        }
    )
    row.google_expires_at = _now() + LOGIN_TTL
    db.commit()
    return accounts


def _login(principal: WizardPrincipal) -> Dict[str, Any]:
    """This session's Google login, or ``LOGIN_REQUIRED``."""
    _require_available()
    row = principal.session
    expires = row.google_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not row.google_encrypted or expires is None or expires <= _now():
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Google again.")
    try:
        return decrypt_secret(row.google_encrypted)
    except Exception:  # noqa: BLE001 - undecryptable: sign in again
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Google again.") from None


def _accounts(api: GoogleAdsClient, access_token: str, dev: bool) -> List[Dict[str, str]]:
    try:
        return api.accessible_accounts(access_token, dev=dev)
    except GoogleAdsError as exc:
        raise _session_error(exc) from None


def _session_error(exc: GoogleAdsError) -> SessionError:
    if exc.code == "token_invalid":
        return SessionError(409, "LOGIN_REQUIRED", "Sign in to Google again.")
    if exc.code == "unreachable":
        return SessionError(502, "google_unreachable", exc.message)
    return SessionError(400, "google_refused", exc.message)


def accounts(principal: WizardPrincipal, *, client: Optional[GoogleAdsClient] = None) -> List[Dict[str, str]]:
    login = _login(principal)
    return _accounts(client or GoogleAdsClient(), login["accessToken"], bool(login.get("dev")))


def _account(api: GoogleAdsClient, login: Dict[str, Any], account_id: str) -> Dict[str, str]:
    """The account, only if the signed-in person can reach it (else 404)."""
    wanted = google_ads.valid_customer_id(account_id)
    found = next(
        (a for a in _accounts(api, login["accessToken"], bool(login.get("dev"))) if a["id"] == wanted),
        None,
    ) if wanted else None
    if found is None:
        raise SessionError(404, "account_not_found", "That Google Ads account is not one you can reach.")
    return found


def _forms(api: GoogleAdsClient, login: Dict[str, Any], account_id: str) -> List[Dict[str, str]]:
    try:
        return api.lead_forms(account_id, login["accessToken"], dev=bool(login.get("dev")))
    except GoogleAdsError as exc:
        raise _session_error(exc) from None


def forms(principal: WizardPrincipal, account_id: str, *, client: Optional[GoogleAdsClient] = None) -> List[Dict[str, str]]:
    api = client or GoogleAdsClient()
    login = _login(principal)
    account = _account(api, login, account_id)
    return _forms(api, login, account["id"])


def _taken_elsewhere(db: Session, tenant_id: str, account_id: str, form_ids: List[str], own_id: Optional[str]) -> bool:
    rows = (
        db.query(LcSource)
        .filter(
            LcSource.tenant_id == tenant_id,
            LcSource.platform == PLATFORM_GOOGLE,
            LcSource.account_ref == account_id,
            LcSource.status != SOURCE_DISCONNECTED,
        )
        .all()
    )
    wanted = set(form_ids)
    return any(r.id != own_id and wanted & set(source_service.picked_forms(r)) for r in rows)


def connect(
    db: Session,
    principal: WizardPrincipal,
    account_id: str,
    form_ids: List[str],
    *,
    client: Optional[GoogleAdsClient] = None,
) -> Tuple[LcSource, List[Dict[str, Any]]]:
    """Make (or reuse) this session's Google source and write the webhook into
    each ticked form. Returns the source and one result per form; a refused
    form is named and the rest still connect."""
    api = client or GoogleAdsClient()
    login = _login(principal)
    account = _account(api, login, account_id)
    picked = [i for i in dict.fromkeys(str(f) for f in (form_ids or [])) if google_ads.valid_asset_id(i)]
    if not picked or len(picked) != len(form_ids or []) or len(picked) > MAX_FORMS:
        raise SessionError(422, "invalid_forms", "Tick at least one lead form.")
    available = {f["id"]: f for f in _forms(api, login, account["id"])}
    if any(f not in available for f in picked):
        raise SessionError(422, "invalid_forms", "Tick lead forms of this Google Ads account.")

    session = principal.session
    source: Optional[LcSource] = None
    if session.source_id:
        source = source_service.get_source(db, principal.tenant_id, session.source_id)
        if source.platform != PLATFORM_GOOGLE:
            raise SessionError(409, "wrong_channel", "This link is for another kind of source.")
        if source.account_ref and source.account_ref != account["id"]:
            raise SessionError(409, "wrong_account", "Pick the Google Ads account this source was connected with.")
    if _taken_elsewhere(db, principal.tenant_id, account["id"], picked, source.id if source else None):
        raise SessionError(409, "source_exists", "A ticked form is already a source here. Untick it or open that source.")

    if source is None:
        source, _url, _key = google_source_service.create_guided_source(
            db, principal.tenant_id, actor=principal.actor, user_id=session.user_id
        )
        session.source_id = source.id
    url, key = google_source_service.inbound_url(source), google_source_service.current_key(source)
    if not key:
        raise SessionError(409, "source_disconnected", "This source is disconnected.")

    results: List[Dict[str, Any]] = []
    for form_id in picked:
        try:
            api.set_webhook(account["id"], form_id, login["accessToken"], url=url, key=key, dev=bool(login.get("dev")))
            results.append({"id": form_id, "name": available[form_id]["name"], "ok": True, "message": None})
        except GoogleAdsError as exc:
            if exc.code == "token_invalid":
                raise _session_error(exc) from None
            results.append({"id": form_id, "name": available[form_id]["name"], "ok": False, "message": exc.message})

    connected = [r["id"] for r in results if r["ok"]]
    config = dict(source.config_json or {})
    kept = source_service.picked_forms(source)
    config["formsMode"] = source_service.FORMS_PICK
    config["formIds"] = list(dict.fromkeys(kept + connected))
    source.config_json = config
    source.mode = "auto"
    source.account_ref = account["id"]
    source.account_name = account["name"][:200]
    source.name = account["name"][:200]
    google_source_service.store_refresh_token(source, login.get("refreshToken"))
    if connected:
        source_service.record_event(
            db, source, source_service.ACTION_FORMS_CHANGED, principal.actor, ",".join(kept) or None, ",".join(config["formIds"])
        )
    db.commit()
    db.refresh(source)
    return source, results


def signed_in_email(principal: WizardPrincipal) -> Optional[str]:
    try:
        return _login(principal).get("email")
    except SessionError:
        return None
