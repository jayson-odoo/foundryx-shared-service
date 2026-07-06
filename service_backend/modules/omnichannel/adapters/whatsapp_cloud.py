"""WhatsApp Cloud API adapter (Meta Graph API).

FoundryX is the Tech Provider: Embedded Signup hands us an auth code which we
exchange for a permanent system-user token against the ONE FoundryX Meta app.

Dev-safe: when ``META_APP_ID``/``META_APP_SECRET`` are unset (local, no Meta app
yet) the adapter returns stub credentials so the flow runs end-to-end without a
real Meta app. Tests inject a fake ``client`` to assert behaviour deterministically.
"""
import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from .base import CodeExchangeError, ConnectionStatus, SendError

logger = logging.getLogger(__name__)


class WhatsAppCloudAdapter:
    channel_type = "WHATSAPP"

    def __init__(self, client: Optional[httpx.Client] = None):
        self._client = client
        self._base = f"https://graph.facebook.com/{settings.meta_graph_version}"

    @property
    def _configured(self) -> bool:
        return bool(settings.meta_app_id and settings.meta_app_secret)

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=10.0)

    def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        if not self._configured:
            # Dev fallback — no Meta app configured yet (see module docstring).
            return {"access_token": f"dev-token-{code}", "dev": True}
        base = {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "code": code,
        }
        # The redirect_uri a JS-SDK code is bound to varies by app config:
        #   - None  → the documented Tech-Provider ES config-code flow
        #   - ""    → the classic FB JS-SDK code (empty redirect_uri)
        #   - origin→ apps with "Use Strict Mode for redirect URIs" on
        # A redirect_uri MISMATCH does NOT consume the code, so we try each in
        # turn and take the first Meta accepts. Every failure is logged with
        # Meta's full error (code/subcode/fbtrace_id) for diagnosis.
        variants: list[Optional[str]] = [None, ""]
        if redirect_uri and redirect_uri not in variants:
            variants.append(redirect_uri)

        client = self._http()
        last_detail = ""
        try:
            for variant in variants:
                params = dict(base)
                if variant is not None:
                    params["redirect_uri"] = variant
                try:
                    resp = client.get(f"{self._base}/oauth/access_token", params=params)
                except httpx.HTTPError as exc:
                    raise CodeExchangeError(f"Could not reach Meta: {exc}") from exc
                if resp.status_code == 200:
                    return {"access_token": resp.json().get("access_token", "")}
                try:
                    err = resp.json().get("error", {})
                    last_detail = err.get("message", "")
                except ValueError:
                    err = {"raw": resp.text[:300]}
                    last_detail = f"Meta returned {resp.status_code}."
                logger.warning(
                    "WA code exchange failed (redirect_uri=%r): %s", variant, err
                )
            raise CodeExchangeError(last_detail or "Code exchange failed.")
        finally:
            if self._client is None:
                client.close()

    def subscribe_webhook(self, credentials: Dict[str, Any], waba_id: str, callback_url: str) -> None:
        if not self._configured or credentials.get("dev"):
            return  # best-effort; no-op in dev
        client = self._http()
        try:
            client.post(
                f"{self._base}/{waba_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
        finally:
            if self._client is None:
                client.close()

    def fetch_phone_details(self, credentials: Dict[str, Any], phone_number_id: str) -> Dict[str, Any]:
        if not self._configured or credentials.get("dev") or not phone_number_id:
            return {}
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{phone_number_id}",
                params={"fields": "display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            return resp.json() if resp.status_code == 200 else {}
        except httpx.HTTPError:
            return {}
        finally:
            if self._client is None:
                client.close()

    def list_waba_numbers(self, credentials: Dict[str, Any], waba_id: str) -> list:
        """List a WABA's phone numbers (id + display_phone_number + verified_name)."""
        if not self._configured or credentials.get("dev") or not waba_id:
            return []
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{waba_id}/phone_numbers",
                params={"fields": "id,display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except httpx.HTTPError:
            return []
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
        template: Optional[Dict[str, Any]] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a text or template message. Returns {"external_message_id": wamid}.

        `template` = {"name": str, "language": str, "components": [...]} per the
        Cloud API shape. `context_message_id` threads a reply (WhatsApp quote).
        Dev mode returns a stub wamid so the flow runs without a Meta app.
        """
        if not self._configured or credentials.get("dev"):
            import uuid

            return {"external_message_id": f"wamid.dev-{uuid.uuid4().hex[:12]}", "dev": True}

        payload: Dict[str, Any] = {"messaging_product": "whatsapp", "to": to}
        if template is not None:
            payload["type"] = "template"
            payload["template"] = {
                "name": template["name"],
                "language": {"code": template.get("language") or "en"},
            }
            if template.get("components"):
                payload["template"]["components"] = template["components"]
        else:
            payload["type"] = "text"
            payload["text"] = {"body": text or ""}
        if context_message_id:
            payload["context"] = {"message_id": context_message_id}

        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{phone_number_id}/messages",
                json=payload,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = ""
                raise SendError(detail or f"Meta returned {resp.status_code}.")
            data = resp.json()
            wamid = (data.get("messages") or [{}])[0].get("id", "")
            return {"external_message_id": wamid}
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def fetch_waba_details(self, credentials: Dict[str, Any], waba_id: str) -> Dict[str, Any]:
        """Fetch the WABA's business account name. Dev stub: canned name."""
        if not self._configured or credentials.get("dev") or not waba_id:
            return {"name": "FoundryX Events (dev sandbox)"}
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{waba_id}",
                params={"fields": "name"},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            return resp.json() if resp.status_code == 200 else {}
        except httpx.HTTPError:
            return {}
        finally:
            if self._client is None:
                client.close()

    # WhatsApp Business Profile fields we mirror (plan 06 §3).
    _PROFILE_FIELDS = "about,address,description,email,vertical,websites,profile_picture_url"

    def get_business_profile(
        self, credentials: Dict[str, Any], phone_number_id: str
    ) -> Dict[str, Any]:
        """GET the WhatsApp Business Profile. Dev stub: canned profile."""
        if not self._configured or credentials.get("dev") or not phone_number_id:
            return {
                "about": "Premier event spaces & concierge in KL.",
                "address": "Level 12, Menara FoundryX, Kuala Lumpur",
                "description": "We host weddings, conferences and galas.",
                "email": "hello@foundryx.example",
                "vertical": "EVENT_PLAN",
                "websites": ["https://foundryx.example"],
                "profile_picture_url": None,
            }
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{phone_number_id}/whatsapp_business_profile",
                params={"fields": self._PROFILE_FIELDS},
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code != 200:
                return {}
            # Cloud API wraps the profile in a single-element `data` array.
            data = resp.json().get("data") or [{}]
            return data[0]
        except httpx.HTTPError:
            return {}
        finally:
            if self._client is None:
                client.close()

    def update_business_profile(
        self, credentials: Dict[str, Any], phone_number_id: str, fields: Dict[str, Any]
    ) -> None:
        """POST changed profile fields to Meta. Dev stub: no-op (local write wins)."""
        if not self._configured or credentials.get("dev") or not phone_number_id:
            return
        payload = {"messaging_product": "whatsapp", **fields}
        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{phone_number_id}/whatsapp_business_profile",
                json=payload,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = ""
                raise SendError(detail or f"Meta returned {resp.status_code}.")
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        """Fetch the WABA's message templates (read-only mirror, decision 11)."""
        if not self._configured or credentials.get("dev") or not waba_id:
            return []
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{waba_id}/message_templates",
                params={
                    "fields": "id,name,language,category,status,quality_score,components",
                    "limit": 100,
                },
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except httpx.HTTPError:
            return []
        finally:
            if self._client is None:
                client.close()

    def create_template(
        self, credentials: Dict[str, Any], waba_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """POST a template for review. Returns {meta_template_id, status}.
        Dev stub: fake id + PENDING (T9)."""
        if not self._configured or credentials.get("dev") or not waba_id:
            import uuid

            return {"meta_template_id": f"mtpl.dev-{uuid.uuid4().hex[:12]}", "status": "PENDING"}
        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{waba_id}/message_templates",
                json=payload,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code not in (200, 201):
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = ""
                raise SendError(detail or f"Meta returned {resp.status_code}.")
            data = resp.json()
            return {"meta_template_id": data.get("id"), "status": (data.get("status") or "PENDING").upper()}
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def edit_template(
        self, credentials: Dict[str, Any], meta_template_id: str, payload: Dict[str, Any]
    ) -> None:
        """Edit an existing template's components → re-enters review. Dev: no-op."""
        if not self._configured or credentials.get("dev") or not meta_template_id:
            return
        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{meta_template_id}",
                json=payload,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = ""
                raise SendError(detail or f"Meta returned {resp.status_code}.")
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def delete_template(
        self, credentials: Dict[str, Any], waba_id: str, name: str,
        meta_template_id: Optional[str] = None,
    ) -> None:
        """Delete a template by name (+ hsm_id when known). Dev: no-op."""
        if not self._configured or credentials.get("dev") or not waba_id:
            return
        params = {"name": name}
        if meta_template_id:
            params["hsm_id"] = meta_template_id
        client = self._http()
        try:
            client.delete(
                f"{self._base}/{waba_id}/message_templates",
                params=params,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
        finally:
            if self._client is None:
                client.close()

    def upload_resumable(
        self, credentials: Dict[str, Any], app_id: str, file_bytes: bytes, mime: str
    ) -> str:
        """Meta resumable upload (`/{app_id}/uploads`) → a file handle for a
        template media-header example. Dev stub: fake handle (T10). Shared
        helper — BL-108 profile-photo upload reuses it."""
        if not self._configured or credentials.get("dev") or not app_id:
            import uuid

            return f"dev-handle-{uuid.uuid4().hex[:16]}"
        token = credentials.get("access_token", "")
        client = self._http()
        try:
            # 1) start an upload session
            start = client.post(
                f"{self._base}/{app_id}/uploads",
                params={"file_length": len(file_bytes), "file_type": mime},
                headers={"Authorization": f"Bearer {token}"},
            )
            if start.status_code != 200:
                raise SendError(f"Upload session failed ({start.status_code}).")
            session_id = start.json().get("id", "")
            # 2) upload the bytes (offset 0); Meta returns {h: <handle>}
            up = client.post(
                f"{self._base}/{session_id}",
                content=file_bytes,
                headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
            )
            if up.status_code != 200:
                raise SendError(f"Upload failed ({up.status_code}).")
            handle = up.json().get("h", "")
            if not handle:
                raise SendError("Upload returned no handle.")
            return handle
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a Graph media id → bytes + mime (two-step: URL then download)."""
        if not self._configured or credentials.get("dev") or not media_id:
            return None
        client = self._http()
        try:
            headers = {"Authorization": f"Bearer {credentials.get('access_token', '')}"}
            meta = client.get(f"{self._base}/{media_id}", headers=headers)
            if meta.status_code != 200:
                return None
            info = meta.json()
            blob = client.get(info.get("url", ""), headers=headers)
            if blob.status_code != 200:
                return None
            return {"content": blob.content, "mime_type": info.get("mime_type", "application/octet-stream")}
        except httpx.HTTPError:
            return None
        finally:
            if self._client is None:
                client.close()

    def parse_inbound(self, payload: Dict[str, Any]) -> list:
        """Normalize a WhatsApp webhook payload → canonical event list.

        Message events: {kind:'message', external_message_id, from, profile_name,
        message_type, body, media_id, reply_to_external_id, timestamp}.
        Status events: {kind:'status', external_message_id, status, error_code,
        error_message}. Unknown shapes yield no events (never raise — webhook
        payloads are attacker-controllable).
        """
        events: list = []
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                field = change.get("field") or ""
                value = change.get("value") or {}
                # Template review/quality/category webhooks (plan 07 T6). These
                # arrive on dedicated `field`s, not the `messages` field.
                if field in (
                    "message_template_status_update",
                    "message_template_quality_update",
                    "message_template_category_update",
                ):
                    kind = {
                        "message_template_status_update": "template_status",
                        "message_template_quality_update": "template_quality",
                        "message_template_category_update": "template_category",
                    }[field]
                    events.append(
                        {
                            "kind": kind,
                            "message_template_id": str(value.get("message_template_id"))
                            if value.get("message_template_id") is not None
                            else None,
                            "name": value.get("message_template_name"),
                            "language": value.get("message_template_language"),
                            "status": (value.get("event") or value.get("new_template_status") or "").upper()
                            or None,
                            "reason": value.get("reason"),
                            "quality": (value.get("new_quality_score") or {}).get("score")
                            if isinstance(value.get("new_quality_score"), dict)
                            else value.get("new_quality_score"),
                            "category": value.get("new_category") or value.get("correct_category"),
                        }
                    )
                    continue
                profiles = {
                    c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in value.get("contacts") or []
                }
                for m in value.get("messages") or []:
                    mtype = (m.get("type") or "text").lower()
                    body: Optional[str] = None
                    media_id: Optional[str] = None
                    if mtype == "text":
                        body = (m.get("text") or {}).get("body")
                    elif mtype in ("image", "video", "audio", "document", "sticker"):
                        media = m.get(mtype) or {}
                        media_id = media.get("id")
                        body = media.get("caption") or media.get("filename")
                    elif mtype == "interactive":
                        inter = m.get("interactive") or {}
                        body = (
                            (inter.get("button_reply") or inter.get("list_reply") or {})
                        ).get("title")
                    elif mtype == "button":
                        body = (m.get("button") or {}).get("text")
                    elif mtype == "reaction":
                        body = (m.get("reaction") or {}).get("emoji")
                    events.append(
                        {
                            "kind": "message",
                            "external_message_id": m.get("id"),
                            "from": m.get("from"),
                            "profile_name": profiles.get(m.get("from")),
                            "message_type": mtype.upper(),
                            "body": body,
                            "media_id": media_id,
                            "reply_to_external_id": (m.get("context") or {}).get("id"),
                            "timestamp": m.get("timestamp"),
                        }
                    )
                for s in value.get("statuses") or []:
                    err = (s.get("errors") or [{}])[0]
                    events.append(
                        {
                            "kind": "status",
                            "external_message_id": s.get("id"),
                            "status": (s.get("status") or "").upper(),
                            "error_code": str(err.get("code")) if err.get("code") else None,
                            "error_message": err.get("title") or err.get("message"),
                        }
                    )
        return events

    def test_connection(self, credentials: Dict[str, Any], phone_number_id: str) -> ConnectionStatus:
        if not self._configured or credentials.get("dev"):
            return ConnectionStatus(ok=True, message="Connected (dev mode — no live Meta call).")
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{phone_number_id}",
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            if resp.status_code == 200:
                return ConnectionStatus(ok=True, message="Reached the number successfully.")
            # Surface Meta's reason (e.g. code 190 bad token, code 100 wrong
            # object id / missing permission) instead of just the status code.
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            return ConnectionStatus(
                ok=False,
                message=detail or f"Meta returned {resp.status_code}.",
            )
        except httpx.HTTPError as exc:
            return ConnectionStatus(ok=False, message=f"Connection error: {exc}")
        finally:
            if self._client is None:
                client.close()


def get_adapter(channel_type: str = "WHATSAPP", client: Optional[httpx.Client] = None):
    """Resolve a channel adapter by type (WhatsApp only for MVP)."""
    if channel_type == "WHATSAPP":
        return WhatsAppCloudAdapter(client=client)
    raise ValueError(f"Unsupported channel type: {channel_type}")
