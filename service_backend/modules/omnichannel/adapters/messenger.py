"""Facebook Messenger adapter (Meta Graph API) - plan 32 / A7a.

Rides the SAME Meta app as WhatsApp (D-A7-1: no `connections` row, no second
credential model) via `MetaGraphMixin` (telemetry, dev-safe gate, HTTP client,
base URL - `meta_graph.py`). Slice S1 shipped inbound parsing
(`parse_inbound`); slice S2 shipped outbound `send` (text + quick replies,
`messaging_type`/`tag` from `messaging_policy.authorize`); slice S3 completes
the connect flow - real `exchange_code` (Facebook Login for Business),
`exchange_long_lived_token`, `list_pages` (`GET /me/accounts` + the linked IG
account) and `subscribe_webhook`/`test_connection` against a live Meta app,
orchestrated by `services/meta_connect_service.py`. Slice S5 completes the
adapter: real `upload_media` (Attachment Upload API, upload BY ID, D-A7-11),
`fetch_media_url` (the SSRF-guarded inbound CDN fetch, D-A7-12), rate-limit
classification (`is_rate_limited_error` in `meta_graph.py`, AC-CHN-51) and
the watermark/`mids` receipt application (`inbound_service._handle_status`,
D-A7-22).

Sources (cited per CLAUDE.md, section 10 of the plan):
- Messenger Platform webhooks (object `page`, `entry[].messaging[]`,
  `X-Hub-Signature-256`):
  https://developers.facebook.com/docs/messenger-platform/webhooks
- Messenger Send API (`POST /{PAGE_ID}/messages`, `recipient.id`,
  `messaging_type`, `tag`, response `message_id`):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Messenger quick replies (`message.quick_replies[]`, `content_type`,
  max 13, 20-character title):
  https://developers.facebook.com/docs/messenger-platform/send-messages/quick-replies
- Messenger/Instagram messaging policy (24h standard window, the Human Agent
  7-day extension, human-only restriction):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
- Facebook Login for Business / long-lived token exchange
  (`grant_type=fb_exchange_token`, non-expiring Page tokens):
  https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
- `GET /me/accounts` (Pages + per-Page access token + linked
  `instagram_business_account`):
  https://developers.facebook.com/docs/graph-api/reference/user/accounts/
- `POST /{page-id}/subscribed_apps` (`subscribed_fields`):
  https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
- Messenger Attachment Upload API (`POST /me/message_attachments`, multipart
  `filedata` + a `message` JSON part naming the Meta attachment type,
  `is_reusable`, response `attachment_id` - upload BY ID, D-A7-11):
  https://developers.facebook.com/docs/messenger-platform/send-messages/saving-assets
- `message_deliveries`/`message_reads` webhook payload shape (`mids`,
  `watermark` in epoch MILLISECONDS - D-A7-22):
  https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/message-deliveries/
  https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/message-reads/
- Graph API error handling / rate limiting (error codes 4/17/32/613, the
  `X-Business-Use-Case-Usage` header - D-A7-12's sibling concern, AC-CHN-51):
  https://developers.facebook.com/docs/graph-api/guides/error-handling
  https://developers.facebook.com/docs/graph-api/overview/rate-limiting
"""
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings
from app.services.url_guard import UrlGuardError, assert_deliverable
from .base import CodeExchangeError, ConnectionStatus, SendError
from .meta_graph import MetaGraphMixin, _meta_error_detail, is_rate_limited_error

logger = logging.getLogger(__name__)


class _TransientFetchError(Exception):
    """An inbound CDN fetch hop hit a transport error or a Meta-side 5xx -
    retried once (bounded) by `fetch_media_url`, never surfaced past it."""


# `subscribed_apps` fields this app asks a connected Page for (plan 32 S3,
# D-A7-15). `message_echoes` is deliberately ABSENT (D-A7-23) - our own
# outbound must never come back as a second inbound bubble, and the parser
# drops an echo unconditionally, so there is nothing to gain from receiving
# it and a real cost (a spurious workflow trigger) if it ever slipped
# through. `message_reads`/`message_deliveries`/`message_reactions` are
# requested now even though the "apply" side (watermark receipts, reactions)
# completes in plan 32 S5 - `parse_inbound` already normalizes them (S1), so
# subscribing early costs nothing and avoids a second Meta App Review pass.
# Source: https://developers.facebook.com/docs/messenger-platform/webhooks
_SUBSCRIBED_FIELDS = "messages,messaging_postbacks,message_reads,message_deliveries,message_reactions"

# Dev-safe canned Facebook Pages (mirrors the S0 frontend mock's
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

# Messenger `attachment.type` -> the house canonical message-type vocabulary
# (plan §5.6). `file` (document) is Messenger-only - Instagram never carries
# it (capability table, §5.5).
_ATTACHMENT_TYPES = {
    "image": "IMAGE",
    "video": "VIDEO",
    "audio": "AUDIO",
    "file": "DOCUMENT",
}

# The house canonical type -> Meta attachment-upload/send ASSET_TYPE (D-A7-11,
# also reused as the multipart upload's "message.attachment.type").
_MIME_ATTACHMENT_TYPE = {"image": "image", "video": "video", "audio": "audio"}

# Meta CDN host allowlist (D-A7-12/AC-CHN-47) - the domains an inbound
# Messenger/Instagram attachment's `payload.url` is EVER hosted on. A URL
# taken from a webhook payload and fetched server-side is an SSRF primitive
# regardless of the payload's signature verification (the house rule from
# `webhook_delivery.assert_deliverable`: re-validate before every fetch, not
# only trust the source), so this allowlist is the FIRST gate - checked again
# at EVERY redirect hop, not only on the original URL.
# Source: https://developers.facebook.com/docs/messenger-platform/webhooks
_CDN_HOST_SUFFIXES = ("fbcdn.net", "fbsbx.com", "cdninstagram.com")

# Meta's own overall attachment ceiling ("Saving Assets" docs: 25MB overall) -
# reused as the inbound fetch cap so a malicious or broken CDN response can
# never make this adapter buffer an unbounded blob in memory; a stream that
# exceeds it is abandoned mid-read (AC-CHN-46/47 "capped read").
_MAX_FETCH_BYTES = 25 * 1024 * 1024
_MAX_FETCH_REDIRECTS = 3
_MAX_FETCH_ATTEMPTS = 2  # one bounded inline retry on a transient CDN hiccup

# Mimes an inbound attachment fetch accepts after sniffing (AC-CHN-46 "images/
# video/audio/pdf per the existing upload allowlist"). A DOCUMENT-typed
# attachment (Messenger-only, `_ATTACHMENT_TYPES["file"]`) additionally rides
# the SAME outbound document family (`media_pipeline.ACCEPTED_MIMES
# ["DOCUMENT"]` - pdf/zip/docx/xlsx/pptx/txt) so an advertised capability
# (`CAPABILITIES["FACEBOOK"].document is True`, the composer offers it) does
# not silently drop every non-pdf inbound file (should-fix, security review
# round 1) - everything else keeps the narrower image/video/audio/pdf set.
_ALLOWED_FETCH_MIME_PREFIXES = ("image/", "video/", "audio/")

# Dev-safe magic recipient (AC-CHN-51) - a workflow/manual test can trigger the
# transient rate-limit path with NO live Meta app by addressing this PSID; the
# dev-stub `_send_impl`/`upload_media` raise the SAME `SendError(transient=
# True)` a real Meta 613/429 would, so `send_runner`'s bounded backoff is
# exercised end to end without a Meta app.
DEV_RATE_LIMIT_PSID = "psid.dev-ratelimit"
_DEV_RATE_LIMIT_MESSAGE = "Calls to this api have exceeded the rate limit."


def _is_meta_cdn_host(host: Optional[str]) -> bool:
    if not host:
        return False
    lowered = host.lower()
    return any(lowered == suffix or lowered.endswith("." + suffix) for suffix in _CDN_HOST_SUFFIXES)


def _is_allowed_fetch_mime(mime: Optional[str], kind: Optional[str] = None) -> bool:
    if not mime:
        return False
    if (kind or "").upper() == "DOCUMENT":
        from ..services.media_pipeline import ACCEPTED_MIMES

        return mime in ACCEPTED_MIMES["DOCUMENT"]
    return mime == "application/pdf" or mime.startswith(_ALLOWED_FETCH_MIME_PREFIXES)


def _error_detail_with_usage(resp: httpx.Response) -> str:
    """`_meta_error_detail` plus, on a throttling response, the
    `X-Business-Use-Case-Usage` consumption snapshot Meta returns alongside
    it (AC-CHN-51 "surfaces Meta's own reason") - appended here rather than
    inside the shared `_meta_error_detail` so WhatsApp's error copy stays
    byte-identical (AC-CHN-23)."""
    detail = _meta_error_detail(resp)
    if is_rate_limited_error(resp):
        usage = resp.headers.get("x-business-use-case-usage")
        if usage:
            detail = f"{detail} (usage: {usage})"
    return detail


class MessengerAdapter(MetaGraphMixin):
    channel_type = "FACEBOOK"

    # ── Onboarding (plan 32 S3 - Facebook Login for Business) ───────────────
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
                return {"access_token": resp.json().get("access_token", "")}
            try:
                err = resp.json().get("error", {})
                detail = err.get("message", "")
            except ValueError:
                err = {"raw": resp.text[:300]}
                detail = f"Meta returned {resp.status_code}."
            logger.warning(
                "Messenger code exchange failed (redirect_uri=%r): %s", redirect_uri, err
            )
            raise CodeExchangeError(detail or "Code exchange failed.")
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
                return {"access_token": resp.json().get("access_token", token)}
            return credentials
        except httpx.HTTPError:
            return credentials
        finally:
            if self._client is None:
                client.close()

    def list_pages(self, credentials: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List the Pages this user token administers, with each Page's OWN
        access token and (when linked) its Instagram professional account -
        `meta_connect_service` maps this into `MetaPageOption` (AC-CHN-32/44).

        Source: https://developers.facebook.com/docs/graph-api/reference/user/accounts/
        https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
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
            return resp.json().get("data") or []
        except httpx.HTTPError as exc:
            raise CodeExchangeError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def subscribe_webhook(self, credentials: Dict[str, Any], page_id: str, callback_url: str) -> None:
        """Best-effort `subscribed_apps` subscription - byte-for-byte the
        WhatsApp `subscribe_webhook` shape (no try/except here; a
        subscription failure must never block the connect, AC-CHN-33, so the
        CALLER, `meta_connect_service.connect`, wraps this call in
        try/except). ``credentials`` carries the PAGE access token (the
        channel's own stored credentials, not the connect session's user
        token) - `page_id` is the Facebook Page id even for an Instagram
        channel (IG messaging is page-linked, D-A7-14/45)."""
        if not self._configured or credentials.get("dev"):
            return  # best-effort; no-op in dev
        client = self._http()
        try:
            client.post(
                f"{self._base}/{page_id}/subscribed_apps",
                params={"subscribed_fields": _SUBSCRIBED_FIELDS},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
        finally:
            if self._client is None:
                client.close()

    def fetch_phone_details(self, credentials: Dict[str, Any], phone_number_id: str) -> Dict[str, Any]:
        return {}  # No phone concept on Messenger.

    def test_connection(self, credentials: Dict[str, Any], routing_id: str) -> ConnectionStatus:
        """``routing_id`` is the Page id (Messenger) or IG account id
        (Instagram) - AC-CHN-37: this pings the page/account, never a phone
        number id, which these channel types never have."""
        if not self._configured or credentials.get("dev"):
            return ConnectionStatus(ok=True, message="Connected (dev mode - no live Meta call).")
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{routing_id}",
                params={"fields": "id,name"},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code == 200:
                return ConnectionStatus(ok=True, message="Reached the page successfully.")
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            return ConnectionStatus(ok=False, message=detail or f"Meta returned {resp.status_code}.")
        except httpx.HTTPError as exc:
            return ConnectionStatus(ok=False, message=f"Connection error: {exc}")
        finally:
            if self._client is None:
                client.close()

    # ── Outbound (plan 32 S2 - window/addressing resolved by the caller;
    #             media-by-id upload is REAL as of plan 32 S5, D-A7-11) ───────
    def upload_media(
        self, credentials: Dict[str, Any], phone_number_id: str, content: bytes, mime: str
    ) -> str:
        """Attachment upload-by-id (D-A7-11 - Meta's Attachment Upload API,
        `POST /me/message_attachments`, never a public URL for Meta to
        fetch): multipart `filedata` + a `message` part naming the Meta
        asset type (`image`/`video`/`audio`, else `file` for documents) and
        `is_reusable`. ``phone_number_id`` is the PAGE_ID whose access token
        authorizes the call (`channel_addressing.sender_ref`), kept as the
        uniform adapter param name. Dev-safe stub unchanged - a fake id so
        `send_runner`'s media branch runs end to end with no Meta app.

        Source: https://developers.facebook.com/docs/messenger-platform/send-messages/saving-assets
        """
        if not self._configured or credentials.get("dev"):
            import uuid

            return f"media.dev-{uuid.uuid4().hex[:12]}"
        att_type = _MIME_ATTACHMENT_TYPE.get((mime or "").split("/")[0], "file")
        message = json.dumps({"attachment": {"type": att_type, "payload": {"is_reusable": True}}})
        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/me/message_attachments",
                data={"message": message},
                files={"filedata": ("upload", content, mime)},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            self._last_http_status = resp.status_code
            if resp.status_code != 200:
                raise SendError(
                    _error_detail_with_usage(resp),
                    transient=resp.status_code >= 500 or is_rate_limited_error(resp),
                )
            attachment_id = resp.json().get("attachment_id", "")
            if not attachment_id:
                raise SendError("Attachment upload returned no id.")
            return attachment_id
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}", transient=True) from exc
        finally:
            if self._client is None:
                client.close()

    def send(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        media: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
        **_ignored: Any,
    ) -> Dict[str, Any]:
        """``phone_number_id`` is actually the PAGE_ID / IG account id
        (`channel_addressing.sender_ref`); ``to`` is the PSID/IGSID
        (`channel_addressing.recipient_ref`) - named to match the uniform
        `ChannelAdapter.send` signature every adapter shares. ``structured``
        is the raw friendly interactive definition (only a ``buttons`` kind
        ever reaches this adapter - `messaging_policy.assert_kind_supported`
        refuses `list`/`cta_url`/`location_request` upstream); it maps onto
        Meta quick replies via `structured.build_quick_replies` (D-A7-13).
        ``messaging_type``/``tag`` are `messaging_policy.authorize`'s
        resolved Meta send parameters, used VERBATIM (never re-derived,
        D-A7-8). ``**_ignored`` absorbs any WhatsApp-only kwarg
        (`template`/`interactive`/`location`/`contacts`/`reaction`) a
        uniform caller might still pass - the capability gate upstream
        guarantees none of those kinds ever reach here for real."""
        return self._graph_call(
            "graph:send",
            lambda: self._send_impl(
                credentials, phone_number_id, to,
                text=text, media=media, structured=structured,
                messaging_type=messaging_type, tag=tag,
                context_message_id=context_message_id,
            ),
            extract_ref=lambda result: (result or {}).get("external_message_id"),
        )

    def _send_impl(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        media: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._configured or credentials.get("dev"):
            import uuid

            # AC-CHN-51 dev-safe rate-limit rehearsal: a workflow/manual test
            # addressing this magic PSID gets the SAME transient SendError a
            # real Meta 613/429 would, with no live Meta app required.
            if to == DEV_RATE_LIMIT_PSID:
                raise SendError(_DEV_RATE_LIMIT_MESSAGE, transient=True)
            return {"external_message_id": f"m.dev-{uuid.uuid4().hex[:12]}", "dev": True}

        from ..services.structured import build_quick_replies

        message: Dict[str, Any] = {}
        quick_replies = build_quick_replies(structured) if structured else None
        if quick_replies:
            message["text"] = (structured or {}).get("body") or text or ""
            message["quick_replies"] = quick_replies
        elif media is not None:
            kind = (media.get("kind") or "").lower()
            att_type = "file" if kind == "document" else kind
            message["attachment"] = {
                "type": att_type,
                "payload": {"attachment_id": media["id"], "is_reusable": True},
            }
        else:
            message["text"] = text or ""
        if context_message_id:
            message["reply_to"] = {"mid": context_message_id}

        body: Dict[str, Any] = {
            "recipient": {"id": to},
            "messaging_type": messaging_type or "RESPONSE",
            "message": message,
        }
        if tag:
            body["tag"] = tag

        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{phone_number_id}/messages",
                json=body,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            self._last_http_status = resp.status_code
            if resp.status_code != 200:
                # AC-CHN-51: a Meta rate-limit/throttling error (code 4/17/32/
                # 613, or a bare 429) is TRANSIENT regardless of HTTP status -
                # `send_runner` requeues it for bounded backoff instead of
                # stamping FAILED.
                raise SendError(
                    _error_detail_with_usage(resp),
                    transient=resp.status_code >= 500 or is_rate_limited_error(resp),
                )
            data = resp.json()
            return {"external_message_id": data.get("message_id", "")}
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}", transient=True) from exc
        finally:
            if self._client is None:
                client.close()

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        # Messenger delivers a short-lived CDN URL inline on the attachment,
        # never a media id to resolve - `fetch_media_url` below is the real
        # inbound path (D-A7-12).
        return None

    # ── Inbound media fetch (plan 32 S5, D-A7-12/AC-CHN-46/47) ──────────────
    def fetch_media_url(
        self, credentials: Dict[str, Any], url: Optional[str], kind: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Download an inbound Messenger/Instagram attachment from the short-
        lived CDN URL Meta embeds in the webhook payload - a fetch target
        taken from attacker-influenced payload data, so it is validated
        BEFORE every attempt and re-validated at EVERY redirect hop: HTTPS
        only, the Meta CDN host allowlist, the shared SSRF guard
        (`url_guard.assert_deliverable`), a capped streaming read, and a
        bounded redirect count (max `_MAX_FETCH_REDIRECTS`). Downloaded WITH
        the page access token (AC-CHN-46). A URL failing validation, a
        content sniff mismatch, or an oversize body returns `None`
        immediately (a PERMANENT rejection - never retried, since retrying a
        rejected host/type wastes a hop for no different outcome); a
        transport error or a Meta-side 5xx is retried once (bounded inline
        retry, AC-CHN-46 "a storage hiccup loses the media, never the
        message"). Never raises - the caller stores the message without
        media on any failure. ``kind`` (the resolved house message type, e.g.
        `"DOCUMENT"`) widens the sniff allowlist for that ONE kind to the
        outbound document family - every other kind keeps the narrower
        image/video/audio/pdf set (should-fix, security review round 1)."""
        if not url:
            return None
        if not self._configured or credentials.get("dev"):
            # Dev-safe (same gate as every other Graph call in this module) -
            # a dev/sandbox channel carries no real page token, so never
            # attempt a real CDN fetch with one; the seeded demo threads stay
            # network-free.
            return None
        headers = {"Authorization": f"Bearer {credentials.get('access_token', '')}"}
        for attempt in range(_MAX_FETCH_ATTEMPTS):
            try:
                return self._fetch_media_once(url, headers, kind=kind)
            except _TransientFetchError as exc:
                if attempt + 1 >= _MAX_FETCH_ATTEMPTS:
                    logger.warning("media URL fetch exhausted retries: %s", exc)
                    return None
                continue
            except Exception:  # noqa: BLE001 - never raise into the inbound pipeline
                logger.exception("media URL fetch failed")
                return None
        return None

    def _fetch_media_once(
        self, url: str, headers: Dict[str, str], *, kind: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        current = url
        client = self._http()
        try:
            for _hop in range(_MAX_FETCH_REDIRECTS + 1):
                parsed = urlparse(current)
                if parsed.scheme != "https" or not _is_meta_cdn_host(parsed.hostname):
                    return None  # AC-CHN-47: non-https / non-Meta-CDN target rejected
                try:
                    assert_deliverable(current, subject="Attachment URL")
                except UrlGuardError:
                    return None  # shared SSRF guard rejected the target
                try:
                    with client.stream("GET", current, headers=headers, follow_redirects=False) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308):
                            location = resp.headers.get("location")
                            if not location:
                                return None
                            current = urljoin(current, location)
                            continue
                        if resp.status_code >= 500:
                            raise _TransientFetchError(f"Meta CDN returned {resp.status_code}")
                        if resp.status_code != 200:
                            return None
                        buf = bytearray()
                        for chunk in resp.iter_bytes():
                            buf.extend(chunk)
                            if len(buf) > _MAX_FETCH_BYTES:
                                return None  # AC-CHN-47 "capped read" - truncated, unavailable
                        content = bytes(buf)
                except httpx.HTTPError as exc:
                    raise _TransientFetchError(str(exc)) from exc
                mime = None
                try:
                    from ..services.media_pipeline import detect_media_mime

                    mime = detect_media_mime(content)
                except Exception:  # noqa: BLE001 - a sniff hiccup is a rejection, not a crash
                    mime = None
                if not _is_allowed_fetch_mime(mime, kind):
                    return None  # sniff mismatch / not on the allowed family for this kind
                return {"content": content, "mime_type": mime}
            return None  # too many redirects
        finally:
            if self._client is None:
                client.close()

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        return []  # No message-template concept on Messenger/Instagram (D-A7-17).

    def fetch_profile_name(
        self, credentials: Dict[str, Any], external_user_id: str
    ) -> Optional[str]:
        """Best-effort ``GET /{PSID}?fields=name`` (AC-CHN-20 "when
        available") - Messenger's webhook payload never carries the sender's
        name inline, unlike WhatsApp's ``contacts[].profile.name``. Dev/
        unconfigured -> ``None`` (the caller falls back to no name, never a
        crash)."""
        if not self._configured or credentials.get("dev") or not external_user_id:
            return None
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{external_user_id}",
                params={"fields": "name", "access_token": credentials.get("access_token", "")},
            )
            if resp.status_code == 200:
                return resp.json().get("name")
            return None
        except httpx.HTTPError:
            return None
        finally:
            if self._client is None:
                client.close()

    # ── Inbound (plan 32 S1) ─────────────────────────────────────────────────
    def parse_inbound(self, payload: Dict[str, Any]) -> list:
        """Normalize a Messenger webhook payload (`entry[].messaging[]`, NOT
        `entry[].changes[]`) into the existing canonical event dicts
        (AC-CHN-18). Never raises - webhook payloads are attacker-controllable
        (a malformed shape yields zero events, AC-CHN-18)."""
        events: list = []
        try:
            for entry in payload.get("entry") or []:
                page_id = entry.get("id")
                for item in entry.get("messaging") or []:
                    event = self._parse_one(item, page_id)
                    if event is not None:
                        events.append(event)
        except (AttributeError, TypeError):
            return []
        return events

    def _parse_one(self, item: Dict[str, Any], page_id: Optional[str]) -> Optional[Dict[str, Any]]:
        sender = (item.get("sender") or {}).get("id")
        if not sender:
            return None
        timestamp = item.get("timestamp")

        message = item.get("message")
        if message is not None:
            # D-A7-23: our own outbound must never come back as a second
            # inbound bubble - dropped in the parser, not downstream.
            if message.get("is_echo"):
                return None
            mid = message.get("mid")
            reply_to = (message.get("reply_to") or {}).get("mid")
            quick_reply = message.get("quick_reply")
            if quick_reply is not None:
                title = message.get("text")
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": "INTERACTIVE_REPLY",
                    "original_type": "quick_reply",
                    "body": title,
                    "payload": {"kind": "quick_reply", "id": quick_reply.get("payload"), "title": title},
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            attachments = message.get("attachments") or []
            if attachments:
                att = attachments[0]
                att_type = (att.get("type") or "").lower()
                url = (att.get("payload") or {}).get("url")
                resolved = _ATTACHMENT_TYPES.get(att_type, "UNSUPPORTED")
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": resolved,
                    "original_type": att_type or "attachment",
                    "body": message.get("text"),
                    "media_url": url,
                    # Not fetched yet (D-A7-12 - the SSRF-guarded fetch lands
                    # in plan 32 S5); persisted as a pending ref so a later
                    # backfill can complete it without re-parsing the payload.
                    # An unmapped attachment kind (`location`, `fallback`, ...
                    # falls through to `UNSUPPORTED` above) carries no `url`
                    # at all - preserve its OWN payload (coordinates, template
                    # data) instead of dropping it, matching the Instagram
                    # adapter's `_ig_placeholder` (AC-CHN-18, nit - security
                    # review round 1).
                    "payload": {"pendingMediaUrl": url} if url else (att.get("payload") or None),
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            if message.get("text") is not None:
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": "TEXT",
                    "original_type": "text",
                    "body": message.get("text"),
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            # A message shape with neither text, attachments nor quick_reply -
            # kept as a placeholder, never dropped (AC-CHN-18).
            return {
                "kind": "message",
                "external_message_id": mid,
                "from": sender,
                "profile_name": None,
                "message_type": "UNSUPPORTED",
                "original_type": "message",
                "body": None,
                "reply_to_external_id": reply_to,
                "timestamp": timestamp,
            }

        postback = item.get("postback")
        if postback is not None:
            title = postback.get("title")
            return {
                "kind": "message",
                # Messenger postbacks carry no `mid` - synthesize a stable,
                # per-event id so idempotency/persistence still have one.
                # Millisecond-timestamp granularity means two postbacks from
                # the SAME sender in the same millisecond collide onto one
                # id (dedupe to one stored row) - an accepted, narrow window
                # given Meta provides nothing finer-grained here (nit,
                # security review round 1).
                "external_message_id": f"psb.{page_id or ''}.{sender}.{timestamp}",
                "from": sender,
                "profile_name": None,
                "message_type": "INTERACTIVE_REPLY",
                "original_type": "postback",
                "body": title,
                "payload": {"kind": "postback", "id": postback.get("payload"), "title": title},
                "timestamp": timestamp,
            }

        delivery = item.get("delivery")
        if delivery is not None:
            # Receipts are parsed now, applied in plan 32 S5 (D-A7-22, the
            # watermark/mids mapping) - no `external_message_id` here means
            # the existing `_handle_status` guard already no-ops these.
            return {
                "kind": "status",
                "status": "DELIVERED",
                "mids": delivery.get("mids") or [],
                "watermark": delivery.get("watermark"),
                "from": sender,
            }

        read = item.get("read")
        if read is not None:
            return {
                "kind": "status",
                "status": "READ",
                "watermark": read.get("watermark"),
                "from": sender,
            }

        reaction = item.get("reaction")
        if reaction is not None:
            action = reaction.get("action")
            return {
                "kind": "reaction",
                "external_message_id": None,
                "from": sender,
                "target_external_id": reaction.get("mid"),
                "emoji": (reaction.get("emoji") or "") if action != "unreact" else "",
                "timestamp": timestamp,
            }

        return None
