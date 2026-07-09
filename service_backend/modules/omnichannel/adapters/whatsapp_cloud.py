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


def _meta_error_detail(resp: "httpx.Response") -> str:
    """Assemble the most specific message Meta gives. ``error.message`` alone is
    often the generic title ("Invalid parameter"); the real reason lives in
    ``error_user_title``/``error_user_msg`` and ``error_data.details``. Surface
    all of them so the operator sees WHY a template was rejected."""
    try:
        err = (resp.json() or {}).get("error", {}) or {}
    except ValueError:
        return f"Meta returned {resp.status_code}."
    parts = []
    for key in ("error_user_title", "error_user_msg"):
        val = (err.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    details = ((err.get("error_data") or {}).get("details") or "").strip()
    if details and details not in parts:
        parts.append(details)
    if not parts:
        msg = (err.get("message") or "").strip()
        parts.append(msg or f"Meta returned {resp.status_code}.")
    return " — ".join(parts)


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
        # Self-hosted redirect flow: the code is minted against a redirect_uri WE
        # own + registered (strict mode requires an EXACT match at exchange), so
        # we send that identical value. Omitting it works only for the (rare)
        # config-code exemption — kept as the fallback when the client sends none.
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
            # Full Meta error (code/subcode/fbtrace_id) for diagnosis.
            logger.warning(
                "WA code exchange failed (redirect_uri=%r): %s", redirect_uri, err
            )
            raise CodeExchangeError(detail or "Code exchange failed.")
        finally:
            if self._client is None:
                client.close()

    def resolve_onboarded_assets(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """After the token exchange, discover WHICH WABA + phone number the token
        grants access to — the self-hosted redirect flow has no postMessage
        session info, so we read it back from the token itself:

          debug_token → granular_scopes[whatsapp_business_*].target_ids → WABA
          → GET /{waba_id}/phone_numbers → phone_number_id + display number

        Returns {} in dev / when nothing resolves; the caller enforces presence.
        """
        token = credentials.get("access_token", "")
        if not token or credentials.get("dev") or not self._configured:
            return {}
        app_token = f"{settings.meta_app_id}|{settings.meta_app_secret}"
        client = self._http()
        try:
            waba_id: Optional[str] = None
            try:
                dbg = client.get(
                    f"{self._base}/debug_token",
                    params={"input_token": token, "access_token": app_token},
                )
                if dbg.status_code == 200:
                    scopes = (dbg.json().get("data") or {}).get("granular_scopes") or []
                    for scope in scopes:
                        if scope.get("scope") in (
                            "whatsapp_business_management",
                            "whatsapp_business_messaging",
                        ):
                            ids = scope.get("target_ids") or []
                            if ids:
                                waba_id = ids[0]
                                break
            except httpx.HTTPError:
                waba_id = None

            phone_number_id: Optional[str] = None
            display: Optional[str] = None
            if waba_id:
                try:
                    pr = client.get(
                        f"{self._base}/{waba_id}/phone_numbers",
                        params={"access_token": token},
                    )
                    if pr.status_code == 200:
                        nums = pr.json().get("data") or []
                        if nums:
                            phone_number_id = nums[0].get("id")
                            display = nums[0].get("display_phone_number")
                except httpx.HTTPError:
                    phone_number_id = None

            return {
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
                "display_phone_number": display,
            }
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

    def upload_media(
        self, credentials: Dict[str, Any], phone_number_id: str, content: bytes, mime: str
    ) -> str:
        """Upload a media blob to ``/{phone_number_id}/media`` → a reusable
        ``media_id`` (the upload-by-id contract, plan 12 AC-12-02). Dev stub:
        fake id so the flow runs without a Meta app."""
        if not self._configured or credentials.get("dev"):
            import uuid

            return f"media.dev-{uuid.uuid4().hex[:12]}"
        token = credentials.get("access_token", "")
        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{phone_number_id}/media",
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": ("upload", content, mime)},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    detail = ""
                raise SendError(
                    detail or f"Media upload failed ({resp.status_code}).",
                    transient=resp.status_code >= 500,
                )
            media_id = resp.json().get("id", "")
            if not media_id:
                raise SendError("Media upload returned no id.")
            return media_id
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
        template: Optional[Dict[str, Any]] = None,
        media: Optional[Dict[str, Any]] = None,
        interactive: Optional[Dict[str, Any]] = None,
        location: Optional[Dict[str, Any]] = None,
        contacts: Optional[list] = None,
        reaction: Optional[Dict[str, Any]] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a text/template/media/interactive/location/contacts message.
        Returns {"external_message_id": wamid}.

        `template` = {"name","language","components"}. `media` = {"kind","id",
        "caption"?,"filename"?}. `interactive` = the Meta interactive object.
        `location` = {"latitude","longitude","name"?,"address"?}. `contacts` = the
        Meta contacts array. `context_message_id` threads a reply (WhatsApp quote).
        Dev mode returns a stub wamid.
        """
        if not self._configured or credentials.get("dev"):
            import uuid

            return {"external_message_id": f"wamid.dev-{uuid.uuid4().hex[:12]}", "dev": True}

        payload: Dict[str, Any] = {"messaging_product": "whatsapp", "to": to}
        if reaction is not None:
            payload["type"] = "reaction"
            payload["reaction"] = {
                "message_id": reaction.get("message_id"),
                "emoji": reaction.get("emoji") or "",
            }
        elif interactive is not None:
            payload["type"] = "interactive"
            payload["interactive"] = interactive
        elif location is not None:
            payload["type"] = "location"
            payload["location"] = location
        elif contacts is not None:
            payload["type"] = "contacts"
            payload["contacts"] = contacts
        elif template is not None:
            payload["type"] = "template"
            payload["template"] = {
                "name": template["name"],
                "language": {"code": template.get("language") or "en"},
            }
            if template.get("components"):
                payload["template"]["components"] = template["components"]
        elif media is not None:
            kind = (media.get("kind") or "").lower()
            # VOICE is uploaded/sent as an audio object; Meta infers "voice" from
            # the ogg/opus payload the pipeline transcodes to.
            wa_type = "audio" if kind == "voice" else kind
            obj: Dict[str, Any] = {"id": media["id"]}
            if media.get("caption") and wa_type in ("image", "video", "document"):
                obj["caption"] = media["caption"]
            if media.get("filename") and wa_type == "document":
                obj["filename"] = media["filename"]
            payload["type"] = wa_type
            payload[wa_type] = obj
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
                raise SendError(
                    detail or f"Meta returned {resp.status_code}.",
                    transient=resp.status_code >= 500,
                )
            data = resp.json()
            wamid = (data.get("messages") or [{}])[0].get("id", "")
            return {"external_message_id": wamid}
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}", transient=True) from exc
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
                raise SendError(_meta_error_detail(resp))
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
                raise SendError(_meta_error_detail(resp))
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
                    if mtype == "reaction":
                        # A reaction is NEVER a message bubble (plan 12 AC-12-19).
                        # Emit a distinct event keyed to the TARGET message wamid;
                        # an empty emoji removes. inbound_service upserts/deletes.
                        rx = m.get("reaction") or {}
                        events.append(
                            {
                                "kind": "reaction",
                                "external_message_id": m.get("id"),
                                "from": m.get("from"),
                                "target_external_id": rx.get("message_id"),
                                "emoji": rx.get("emoji") or "",
                                "timestamp": m.get("timestamp"),
                            }
                        )
                        continue
                    body: Optional[str] = None
                    media_id: Optional[str] = None
                    media_mime: Optional[str] = None
                    media_filename: Optional[str] = None
                    payload_data: Optional[Dict[str, Any]] = None
                    voice = False
                    resolved_type = mtype.upper()
                    if mtype == "text":
                        body = (m.get("text") or {}).get("body")
                    elif mtype in ("image", "video", "audio", "document", "sticker"):
                        media = m.get(mtype) or {}
                        media_id = media.get("id")
                        body = media.get("caption") or media.get("filename")
                        media_mime = media.get("mime_type")
                        media_filename = media.get("filename")
                        # An inbound audio flagged voice==true is a voice note
                        # (plan 12 AC-12-09) — store it as VOICE, not AUDIO.
                        if mtype == "audio" and bool(media.get("voice")):
                            voice = True
                            resolved_type = "VOICE"
                    elif mtype == "interactive":
                        # A recipient tapped a reply-button or picked a list row
                        # (plan 12 AC-12-14) → INTERACTIVE_REPLY, threaded via context.
                        inter = m.get("interactive") or {}
                        br = inter.get("button_reply")
                        lr = inter.get("list_reply")
                        reply = br or lr or {}
                        resolved_type = "INTERACTIVE_REPLY"
                        body = reply.get("title")
                        payload_data = {
                            "kind": "button" if br else "list",
                            "id": reply.get("id"),
                            "title": reply.get("title"),
                            "description": reply.get("description"),
                        }
                    elif mtype == "location":
                        loc = m.get("location") or {}
                        resolved_type = "LOCATION"
                        payload_data = {
                            "lat": loc.get("latitude"),
                            "lng": loc.get("longitude"),
                            "name": loc.get("name"),
                            "address": loc.get("address"),
                        }
                        body = loc.get("name") or loc.get("address")
                    elif mtype == "contacts":
                        contact_list = m.get("contacts") or []
                        resolved_type = "CONTACTS"
                        payload_data = {"contacts": contact_list}
                        first = (contact_list[0].get("name") or {}) if contact_list else {}
                        body = first.get("formatted_name")
                    elif mtype == "button":
                        # A quick-reply button tap on a template message.
                        body = (m.get("button") or {}).get("text")
                    else:
                        # Unsupported inbound type (order/system/ephemeral/…) — kept
                        # as a placeholder, never silently dropped (plan 12 AC-12-17).
                        resolved_type = "UNSUPPORTED"
                    events.append(
                        {
                            "kind": "message",
                            "external_message_id": m.get("id"),
                            "from": m.get("from"),
                            "profile_name": profiles.get(m.get("from")),
                            "message_type": resolved_type,
                            "original_type": mtype,
                            "body": body,
                            "media_id": media_id,
                            "media_mime": media_mime,
                            "media_filename": media_filename,
                            "payload": payload_data,
                            "voice": voice,
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
