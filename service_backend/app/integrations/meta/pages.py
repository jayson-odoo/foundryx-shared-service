"""Facebook Login for Business + Page plumbing - CORE since plan 64 (D3, D15).

Moved from ``modules/omnichannel/adapters/messenger.py`` (plan 32 S3):
``exchange_code``, ``exchange_long_lived_token`` and ``list_pages`` are a pure
move (``MessengerAdapter`` now inherits them from ``MetaPagesMixin``). The old
fire-and-forget ``subscribed_apps`` POST is replaced by ``subscribe_page_fields``
/ ``unsubscribe_page_fields`` (D15, review R1): Meta keeps ONE
``subscribed_fields`` set per (Page, app), and a POST REPLACES it, so two
features of the same app (omnichannel Messenger ``messages``, Lead Capture
``leadgen``) would silently unsubscribe each other. Both functions therefore
read the current set first and post the union / remainder.

Dev stub rule unchanged: with ``META_APP_ID``/``META_APP_SECRET`` unset (or a
``dev`` credential) nothing calls Meta.

Sources:
- Long-lived token exchange (``grant_type=fb_exchange_token``):
  https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
- ``GET /me/accounts``:
  https://developers.facebook.com/docs/graph-api/reference/user/accounts/
- ``GET``/``POST``/``DELETE /{page-id}/subscribed_apps`` (``subscribed_fields``
  replaces the app's whole set on POST):
  https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Set

import httpx

from app.config import settings
from .errors import CodeExchangeError
from .graph import (
    MetaGraphMixin,
    _dict_items,
    _id_field,
    _json_obj,
    _list_field,
    _meta_error_detail,
    _meta_error_obj,
    _meta_error_text,
    _str_field,
)

logger = logging.getLogger(__name__)

# Dev-safe canned Facebook Pages (mirrors the omnichannel S0 frontend mock's
# MOCK_META_PAGES ids/names 1:1 so a manual dev run and the mock behave the
# same) - returned by `list_pages` whenever the Meta app is unconfigured or
# the session's exchanged token carries `dev` (AC-CHN-35).
_DEV_PAGES: List[Dict[str, Any]] = [
    {
        "id": "pg-701",
        "name": "Foundryx Events Co.",
        "access_token": "dev-page-token-701",
        "instagram_business_account": {"id": "ig-701", "username": "foundryx.events"},
    },
    {
        "id": "pg-702",
        "name": "Foundryx Concierge",
        "access_token": "dev-page-token-702",
        "instagram_business_account": {"id": "ig-702", "username": "foundryx.concierge"},
    },
    {"id": "pg-703", "name": "Foundryx VIP Desk", "access_token": "dev-page-token-703"},
]


# ── Known Page fields per feature (the GET-failed fallback, D15) ────────────
# Each feature that subscribes Page fields declares them here at import/boot.
# When the current set cannot be read, a subscribe posts the requested fields
# PLUS every declared field, so a failed read can never drop another feature's
# subscription (it may at worst keep a field nobody needs any more).
_KNOWN_PAGE_FIELDS: Dict[str, Set[str]] = {}


def register_page_fields(provider_module: str, fields: Iterable[str]) -> None:
    """Declare the Page ``subscribed_fields`` a feature uses. Idempotent."""
    _KNOWN_PAGE_FIELDS.setdefault(provider_module, set()).update(_clean_fields(fields))


def known_page_fields() -> List[str]:
    """Every declared field, sorted (deterministic POST body)."""
    out: Set[str] = set()
    for fields in _KNOWN_PAGE_FIELDS.values():
        out |= fields
    return sorted(out)


def _clean_fields(fields: Iterable[str]) -> List[str]:
    """Split a comma string or iterable into stripped, non-empty, de-duplicated
    field names, first-seen order kept."""
    if isinstance(fields, str):
        fields = fields.split(",")
    out: List[str] = []
    for f in fields:
        name = f.strip() if isinstance(f, str) else ""
        if name and name not in out:
            out.append(name)
    return out


class MetaPagesMixin(MetaGraphMixin):
    """Facebook Login for Business + Page subscription calls. Mixed into
    omnichannel's ``MessengerAdapter`` and usable on its own (``MetaPages()``)
    by any Service that needs a Page token without importing omnichannel."""

    # ── Onboarding (moved from MessengerAdapter, plan 32 S3) ────────────────
    def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """Exchange the popup's auth code for a (short-lived) user access
        token - byte-for-byte the WhatsApp Embedded Signup exchange
        (`WhatsAppCloudAdapter.exchange_code`), since both ride the SAME Meta
        app/client credentials (D-A7-1).

        Source: https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
        """
        if not self._configured:
            return {"access_token": f"dev-token-{code}", "dev": True}
        params = {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "code": code,
        }
        if redirect_uri:
            params["redirect_uri"] = redirect_uri

        client = self._http()
        try:
            try:
                resp = client.get(f"{self._base}/oauth/access_token", params=params)
            except httpx.HTTPError as exc:
                raise CodeExchangeError(f"Could not reach Meta: {exc}") from exc
            if resp.status_code == 200:
                return {"access_token": _str_field(_json_obj(resp), "access_token")}
            err = _meta_error_obj(resp) or {"raw": resp.text[:300]}
            detail = _meta_error_text(resp) or f"Meta returned {resp.status_code}."
            logger.warning(
                "Messenger code exchange failed (redirect_uri=%r): %s", redirect_uri, err
            )
            raise CodeExchangeError(detail)
        finally:
            if self._client is None:
                client.close()

    def exchange_long_lived_token(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Trade the short-lived user token for a long-lived one (~60 days) so
        the Page access tokens `list_pages` returns are effectively
        non-expiring (Meta: "Long-lived Page access tokens do not have an
        expiration date"). Dev / unconfigured -> the credentials unchanged.

        Source: https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
        """
        token = credentials.get("access_token", "")
        if not token or credentials.get("dev") or not self._configured:
            return credentials
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "fb_exchange_token": token,
                },
            )
            if resp.status_code == 200:
                return {"access_token": _str_field(_json_obj(resp), "access_token", token)}
            return credentials
        except httpx.HTTPError:
            return credentials
        finally:
            if self._client is None:
                client.close()

    def list_pages(self, credentials: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List the Pages this user token administers, with each Page's OWN
        access token and (when linked) its Instagram professional account.

        Source: https://developers.facebook.com/docs/graph-api/reference/user/accounts/
        """
        if not self._configured or credentials.get("dev"):
            return [dict(p) for p in _DEV_PAGES]
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/me/accounts",
                params={
                    "fields": "id,name,access_token,instagram_business_account{id,username}",
                    "access_token": credentials.get("access_token", ""),
                },
            )
            if resp.status_code != 200:
                raise CodeExchangeError(_meta_error_detail(resp))
            return _dict_items(_list_field(_json_obj(resp), "data"))
        except httpx.HTTPError as exc:
            raise CodeExchangeError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    # ── Page subscription (D15 - union, never replace) ──────────────────────
    def _current_page_fields(self, client: httpx.Client, page_token: str, page_id: str) -> Optional[List[str]]:
        """This app's current ``subscribed_fields`` on the Page; ``[]`` when the
        app is not subscribed at all; ``None`` when the set cannot be read
        (transport error, non-200, malformed body). Never raises."""
        try:
            resp = client.get(
                f"{self._base}/{page_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {page_token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning("Page %s subscribed_apps read failed: %s", page_id, type(exc).__name__)
            return None
        if resp.status_code != 200:
            logger.warning("Page %s subscribed_apps read returned %s", page_id, resp.status_code)
            return None
        body = _json_obj(resp)
        if not isinstance(body.get("data"), list):
            logger.warning("Page %s subscribed_apps read had no data list", page_id)
            return None
        for app in _dict_items(body["data"]):
            if _id_field(app, "id") == str(settings.meta_app_id):
                return _clean_fields(
                    [f for f in _list_field(app, "subscribed_fields") if isinstance(f, str)]
                )
        return []

    def _post_page_fields(self, client: httpx.Client, page_token: str, page_id: str, fields: List[str]) -> bool:
        resp = client.post(
            f"{self._base}/{page_id}/subscribed_apps",
            params={"subscribed_fields": ",".join(fields)},
            headers={"Authorization": f"Bearer {page_token}"},
        )
        if resp.status_code != 200:
            logger.warning("Page %s subscribed_apps update returned %s", page_id, resp.status_code)
            return False
        return True

    def subscribe_page_fields(
        self, page_token: str, page_id: str, fields: Iterable[str], *, dev: bool = False
    ) -> Optional[List[str]]:
        """Add ``fields`` to this app's Page subscription WITHOUT dropping any
        field already there (another feature's). Returns the field set posted,
        or ``None`` in dev / unconfigured (no Meta call) or when Meta refused
        the update. A transport error on the POST propagates - callers keep
        the best-effort rule (AC-CHN-33) by wrapping the call."""
        requested = _clean_fields(fields)
        if not self._configured or dev:
            return None
        client = self._http()
        try:
            current = self._current_page_fields(client, page_token, page_id)
            if current is None:
                logger.warning(
                    "Page %s: current subscription unknown, posting requested + known fields", page_id
                )
                base = known_page_fields()
            else:
                base = current
            union = list(base) + [f for f in requested if f not in base]
            return union if self._post_page_fields(client, page_token, page_id, union) else None
        finally:
            if self._client is None:
                client.close()

    def unsubscribe_page_fields(
        self, page_token: str, page_id: str, fields: Iterable[str], *, dev: bool = False
    ) -> Optional[List[str]]:
        """Remove ``fields`` from this app's Page subscription, keeping every
        other field. Posts the remainder, or ``DELETE``s the app's subscription
        when nothing remains. Returns the remainder (``[]`` after a delete), or
        ``None`` in dev / unconfigured or when Meta refused the update."""
        drop = set(_clean_fields(fields))
        if not self._configured or dev:
            return None
        client = self._http()
        try:
            current = self._current_page_fields(client, page_token, page_id)
            if current is None:
                logger.warning(
                    "Page %s: current subscription unknown, keeping known fields", page_id
                )
                current = known_page_fields()
            remainder = [f for f in current if f not in drop]
            if remainder:
                ok = self._post_page_fields(client, page_token, page_id, remainder)
                return remainder if ok else None
            resp = client.delete(
                f"{self._base}/{page_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {page_token}"},
            )
            if resp.status_code != 200:
                logger.warning("Page %s subscribed_apps delete returned %s", page_id, resp.status_code)
                return None
            return []
        finally:
            if self._client is None:
                client.close()


class MetaPages(MetaPagesMixin):
    """Standalone Page client for Services that are not omnichannel adapters."""


def subscribe_page_fields(
    page_token: str,
    page_id: str,
    fields: Iterable[str],
    *,
    dev: bool = False,
    client: Optional[httpx.Client] = None,
) -> Optional[List[str]]:
    """Module-level form of ``MetaPagesMixin.subscribe_page_fields``."""
    return MetaPages(client=client).subscribe_page_fields(page_token, page_id, fields, dev=dev)


def unsubscribe_page_fields(
    page_token: str,
    page_id: str,
    fields: Iterable[str],
    *,
    dev: bool = False,
    client: Optional[httpx.Client] = None,
) -> Optional[List[str]]:
    """Module-level form of ``MetaPagesMixin.unsubscribe_page_fields``."""
    return MetaPages(client=client).unsubscribe_page_fields(page_token, page_id, fields, dev=dev)
