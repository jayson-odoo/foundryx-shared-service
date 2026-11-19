"""Google calls the Lead Capture Google sign-in needs (plan 68).

- OAuth 2.0 web server flow: the code is exchanged server-side at
  ``https://oauth2.googleapis.com/token`` (doc:
  https://developers.google.com/identity/protocols/oauth2/web-server).
- Google Ads API REST (doc: https://developers.google.com/google-ads/api/rest/overview):
  ``customers:listAccessibleCustomers``, ``googleAds:search`` (GAQL) for account
  names and LEAD_FORM assets, ``assets:mutate`` to set a lead form's webhook
  delivery (G1 - writable on an existing form is confirmed by spike S-GOOGLE).

Every token rides the ``Authorization`` header, never the URL. Errors carry a
short code and a plain message, never a token or a body.

Dev rule (same as Meta): with ``GOOGLE_ADS_CLIENT_ID`` unset, or a ``dev``
credential, nothing calls Google and canned answers come back.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ADS_BASE = "https://googleads.googleapis.com"
ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
# Plan 68 G-D2: Google Ads + who signed in (shown on the done screen).
LOGIN_SCOPES = (ADS_SCOPE, "openid", "email")
# Google's lead form webhook payload version we read (card 68a).
PAYLOAD_SCHEMA_VERSION = 3
_TIMEOUT = 15.0
_CUSTOMER_RE = re.compile(r"^[0-9]{1,20}$")
_ASSET_RE = re.compile(r"^[0-9]{1,30}$")

# Simulated accounts and forms (no Google client configured: dev + tests).
DEV_ACCOUNTS: List[Dict[str, str]] = [
    {"id": "1000000001", "name": "Sample Ads Account"},
    {"id": "1000000002", "name": "Sample Store Ads"},
]
DEV_FORMS: List[Dict[str, str]] = [
    {"id": "40000000001", "name": "Sample lead form"},
    {"id": "40000000002", "name": "Sample quote form"},
]
DEV_EMAIL = "signed-in@example.com"


class GoogleAdsError(Exception):
    """``code``: ``login_failed`` | ``token_invalid`` | ``refused`` |
    ``unreachable``. ``message`` is safe to show and to log."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def configured() -> bool:
    return bool(settings.google_ads_client_id)


def valid_customer_id(value: Any) -> Optional[str]:
    text = str(value or "").replace("-", "").strip()
    return text if _CUSTOMER_RE.fullmatch(text) else None


def valid_asset_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text if _ASSET_RE.fullmatch(text) else None


class GoogleAdsClient:
    def __init__(self, client: Optional[httpx.Client] = None):
        self._client = client

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=_TIMEOUT)

    # ── OAuth ───────────────────────────────────────────────────────────────
    def exchange_code(self, code: str, redirect_uri: Optional[str]) -> Dict[str, Any]:
        """``{"accessToken", "refreshToken", "scopes": [..], "dev"}``."""
        if not configured():
            return {"accessToken": "dev", "refreshToken": "dev", "scopes": list(LOGIN_SCOPES), "dev": True}
        try:
            res = self._http().post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_ads_client_id,
                    "client_secret": settings.google_ads_client_secret,
                    "redirect_uri": redirect_uri or "",
                    "grant_type": "authorization_code",
                },
            )
        except httpx.HTTPError:
            raise GoogleAdsError("unreachable", "Google could not be reached. Try again.") from None
        body = _json(res)
        if res.status_code != 200 or not body.get("access_token"):
            raise GoogleAdsError("login_failed", "Google did not finish the sign-in. Try again.")
        return {
            "accessToken": str(body["access_token"]),
            "refreshToken": str(body.get("refresh_token") or ""),
            "scopes": str(body.get("scope") or "").split(),
            "dev": False,
        }

    def refresh(self, refresh_token: str) -> str:
        """A fresh access token from a stored refresh token."""
        if not configured():
            return "dev"
        try:
            res = self._http().post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.google_ads_client_id,
                    "client_secret": settings.google_ads_client_secret,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError:
            raise GoogleAdsError("unreachable", "Google could not be reached. Try again.") from None
        body = _json(res)
        if res.status_code != 200 or not body.get("access_token"):
            raise GoogleAdsError("token_invalid", "Google stopped sharing this account. Sign in again.")
        return str(body["access_token"])

    def email(self, access_token: str, *, dev: bool) -> Optional[str]:
        if dev:
            return DEV_EMAIL
        try:
            res = self._http().get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError:
            return None
        value = _json(res).get("email") if res.status_code == 200 else None
        return str(value)[:254] if value else None

    # ── Google Ads API ──────────────────────────────────────────────────────
    def _headers(self, access_token: str) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": settings.google_ads_developer_token,
        }
        manager = valid_customer_id(settings.google_ads_login_customer_id)
        if manager:
            headers["login-customer-id"] = manager
        return headers

    def _url(self, path: str) -> str:
        return f"{ADS_BASE}/{settings.google_ads_api_version}/{path}"

    def _call(self, method: str, path: str, access_token: str, json_body: Optional[dict] = None) -> Dict[str, Any]:
        try:
            res = self._http().request(method, self._url(path), headers=self._headers(access_token), json=json_body)
        except httpx.HTTPError:
            raise GoogleAdsError("unreachable", "Google Ads could not be reached. Try again.") from None
        body = _json(res)
        if res.status_code in (401,):
            raise GoogleAdsError("token_invalid", "Google stopped sharing this account. Sign in again.")
        if res.status_code != 200:
            logger.info("google ads %s %s refused (status %s)", method, path.split("/")[-1], res.status_code)
            raise GoogleAdsError("refused", _refusal_text(body))
        return body

    def accessible_accounts(self, access_token: str, *, dev: bool) -> List[Dict[str, str]]:
        """Accounts the signed-in person can reach, ids + names."""
        if dev:
            return [dict(a) for a in DEV_ACCOUNTS]
        body = self._call("GET", "customers:listAccessibleCustomers", access_token)
        ids = []
        for name in body.get("resourceNames") or []:
            cid = valid_customer_id(str(name).rsplit("/", 1)[-1])
            if cid:
                ids.append(cid)
        out = []
        for cid in ids[:50]:
            try:
                rows = self._search(cid, access_token, "SELECT customer.id, customer.descriptive_name FROM customer")
            except GoogleAdsError:
                rows = []  # an account it cannot read is still listed by id
            name = next((str((r.get("customer") or {}).get("descriptiveName") or "") for r in rows), "")
            out.append({"id": cid, "name": name or cid})
        return out

    def lead_forms(self, customer_id: str, access_token: str, *, dev: bool) -> List[Dict[str, str]]:
        if dev:
            return [dict(f) for f in DEV_FORMS]
        rows = self._search(
            customer_id,
            access_token,
            "SELECT asset.id, asset.name, asset.lead_form_asset.headline FROM asset WHERE asset.type = 'LEAD_FORM'",
        )
        out = []
        for r in rows:
            asset = r.get("asset") or {}
            aid = valid_asset_id(asset.get("id"))
            if not aid:
                continue
            lead = asset.get("leadFormAsset") or {}
            out.append({"id": aid, "name": str(asset.get("name") or lead.get("headline") or aid)[:200]})
        return out

    def set_webhook(self, customer_id: str, asset_id: str, access_token: str, *, url: str, key: str, dev: bool) -> None:
        """Point one lead form's webhook delivery at our URL + key (G-D5)."""
        if dev:
            return
        self._call(
            "POST",
            f"customers/{customer_id}/assets:mutate",
            access_token,
            {
                "operations": [
                    {
                        "update": {
                            "resourceName": f"customers/{customer_id}/assets/{asset_id}",
                            "leadFormAsset": {
                                "deliveryMethods": [
                                    {
                                        "webhook": {
                                            "advertiserWebhookUrl": url,
                                            "googleSecret": key,
                                            "payloadSchemaVersion": PAYLOAD_SCHEMA_VERSION,
                                        }
                                    }
                                ]
                            },
                        },
                        "updateMask": "lead_form_asset.delivery_methods",
                    }
                ]
            },
        )

    def _search(self, customer_id: str, access_token: str, query: str) -> List[Dict[str, Any]]:
        body = self._call("POST", f"customers/{customer_id}/googleAds:search", access_token, {"query": query})
        results = body.get("results")
        return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def _json(res: httpx.Response) -> Dict[str, Any]:
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _refusal_text(body: Dict[str, Any]) -> str:
    """Google's own message, cut short (never the body)."""
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = str(err.get("message") or "").strip().splitlines()[0:1]
    text = message[0][:200] if message else ""
    return text or "Google Ads refused the change."
