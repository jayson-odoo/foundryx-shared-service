"""Meta Graph calls Lead Capture needs (plan 64 L3), on the core Graph plumbing.

Every token rides the ``Authorization`` header, never the URL, so no token can
reach an access log or an httpx INFO line. Errors carry Meta's code and a
sanitised message only (``provider_error_text``), never the token or the body.

Facts (S-META, 15 Nov 2026):
- F4: a system-user token gives the Page token via ``GET /{page}?fields=access_token``
  (the Page must be an asset of the system user). Page edges need the Page token.
- F6: the ``leadgen`` webhook carries ids only; the lead is read with
  ``GET /{leadgen_id}``.
- F7/F9: a Meta test lead has no ``ad_id`` and ``is_organic: true``; the only
  reliable marker is that ``GET /{form_id}/test_leads`` lists it.

Dev rule (same as core): with ``META_APP_ID``/``META_APP_SECRET`` unset, or a
``dev`` credential, nothing calls Meta and canned answers come back.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

import httpx

from app.integrations.meta.graph import (
    MetaGraphMixin,
    _dict_items,
    _error_code,
    _id_field,
    _json_obj,
    _list_field,
    _meta_error_obj,
    _meta_error_text,
    _str_field,
    provider_error_text,
)

logger = logging.getLogger(__name__)

LEAD_FIELDS = "id,created_time,field_data,form_id,ad_id,adset_id,campaign_id,is_organic,platform"
# Graph codes meaning the token no longer works or lost a permission.
TOKEN_ERROR_CODES = {10, 102, 190, 200}
# S-META F7 test-lead subcodes.
SUBCODE_TEST_LEAD_EXISTS = 1892058  # POST /{form}/test_leads: one already exists
SUBCODE_DELETE_NOT_TRUSTED = 1892035  # DELETE /{lead}: "Could Not Delete Lead", yet usually deleted
_TEXT_CAP = 500


class MetaLeadError(Exception):
    """A Graph call failed. ``token_invalid`` = the token or permission is the
    cause (AC-64-29 later); ``message`` is safe to show and to log."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[int] = None,
        subcode: Optional[int] = None,
        token_invalid: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.subcode = subcode
        self.token_invalid = token_invalid


def _error_subcode(resp: httpx.Response) -> Optional[int]:
    sub = _meta_error_obj(resp).get("error_subcode")
    if isinstance(sub, bool):
        return None
    if isinstance(sub, int):
        return sub
    if isinstance(sub, str) and sub.isascii() and sub.isdigit() and len(sub) <= 12:
        return int(sub)
    return None


def _error(resp: httpx.Response, fallback: str) -> MetaLeadError:
    code = _error_code(resp)
    text = provider_error_text(_meta_error_text(resp)) or fallback
    return MetaLeadError(
        text, code=code, subcode=_error_subcode(resp), token_invalid=code in TOKEN_ERROR_CODES
    )


def _text(value: Any) -> str:
    return value.strip()[:_TEXT_CAP] if isinstance(value, str) else ""


def _question(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One Instant Form question as ``{key, label, type, options}``; options
    only ``{key, value}`` strings. A question with no key is dropped (nothing
    could be mapped to it)."""
    key = _text(item.get("key"))
    if not key:
        return None
    options = []
    for opt in _dict_items(item.get("options")):
        okey, value = _text(opt.get("key")), _text(opt.get("value"))
        if okey or value:
            options.append({"key": okey or value, "value": value or okey})
    return {"key": key, "label": _text(item.get("label")) or key, "type": _text(item.get("type")), "options": options}


def dev_questions() -> List[Dict[str, Any]]:
    return [
        {"key": "full_name", "label": "Full name", "type": "FULL_NAME", "options": []},
        {"key": "email", "label": "Email", "type": "EMAIL", "options": []},
        {"key": "phone_number", "label": "Phone number", "type": "PHONE", "options": []},
    ]


def dev_lead(leadgen_id: str, form_id: str) -> Dict[str, Any]:
    """The canned lead the dev stub returns (shape of the S-META fixture,
    fake values only)."""
    return {
        "id": leadgen_id,
        "created_time": "2026-11-15T05:19:11+0000",
        "form_id": form_id,
        "is_organic": True,
        "field_data": [
            {"name": "full_name", "values": ["Test Lead"]},
            {"name": "email", "values": ["lead.test@example.com"]},
            {"name": "phone_number", "values": ["+60120000000"]},
        ],
    }


class MetaLeadClient(MetaGraphMixin):
    @property
    def configured(self) -> bool:
        """A real Meta app is set (else every call is the dev stub)."""
        return self._configured

    def _get(self, path: str, token: str, params: Optional[Dict[str, str]] = None) -> httpx.Response:
        client = self._http()
        try:
            return client.get(
                f"{self._base}/{path}",
                params=params or {},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise MetaLeadError(f"Could not reach Meta ({type(exc).__name__}).") from None
        finally:
            if self._client is None:
                client.close()

    def _send(self, method: str, path: str, token: str) -> httpx.Response:
        client = self._http()
        try:
            return client.request(method, f"{self._base}/{path}", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise MetaLeadError(f"Could not reach Meta ({type(exc).__name__}).") from None
        finally:
            if self._client is None:
                client.close()

    def page_token(self, system_user_token: str, page_id: str, *, dev: bool = False) -> Dict[str, str]:
        """``{"pageToken", "pageName"}`` for a Page the system user holds."""
        if not self._configured or dev:
            return {"pageToken": f"dev-page-token-{page_id}", "pageName": f"Dev Page {page_id}"}
        resp = self._get(page_id, system_user_token, {"fields": "access_token,name"})
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the Page.")
        body = _json_obj(resp)
        token = _str_field(body, "access_token")
        if not token:
            raise MetaLeadError(
                "Meta gave no Page token. Add the Page to the system user's assets.",
                token_invalid=True,
            )
        return {"pageToken": token, "pageName": _str_field(body, "name")}

    def get_lead(self, page_token: str, leadgen_id: str, form_id: str = "", *, dev: bool = False) -> Dict[str, Any]:
        if not self._configured or dev:
            return dev_lead(leadgen_id, form_id)
        resp = self._get(leadgen_id, page_token, {"fields": LEAD_FIELDS})
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the lead read.")
        body = _json_obj(resp)
        if _id_field(body, "id") != leadgen_id:
            raise MetaLeadError("Meta answered with another lead.")
        return body

    def form_name(self, page_token: str, form_id: str, *, dev: bool = False) -> Optional[str]:
        """The Instant Form's name (``GET /{form_id}?fields=name``, Page token),
        or None when it cannot be read. Never raises: a missing name must never
        block a lead."""
        if not form_id:
            return None
        if not self._configured or dev:
            return f"Dev form {form_id}"
        try:
            resp = self._get(form_id, page_token, {"fields": "name"})
        except MetaLeadError:
            return None
        if resp.status_code != 200:
            logger.info("form name read returned %s", resp.status_code)
            return None
        name = _str_field(_json_obj(resp), "name").strip()
        return name[:200] or None

    def test_lead_ids(self, page_token: str, form_id: str, *, dev: bool = False) -> Optional[Set[str]]:
        """Ids of the form's Meta test leads, or None when they cannot be read."""
        if not form_id:
            return None
        if not self._configured or dev:
            return None
        try:
            resp = self._get(f"{form_id}/test_leads", page_token, {"fields": "id"})
        except MetaLeadError:
            return None
        if resp.status_code != 200:
            logger.info("test_leads read for a form returned %s", resp.status_code)
            return None
        return {
            i for i in (_id_field(item, "id") for item in _dict_items(_list_field(_json_obj(resp), "data"))) if i
        }

    # ── form questions + test lead (AC-64-24/30) ───────────────────────────

    def form_questions(self, page_token: str, form_id: str, *, dev: bool = False) -> Dict[str, Any]:
        """``{"formName", "questions": [{key, label, type, options}]}`` read with
        ``GET /{form}?fields=name,questions`` (Page token). Raises MetaLeadError."""
        if not self._configured or dev:
            return {"formName": f"Dev form {form_id}", "questions": dev_questions()}
        resp = self._get(form_id, page_token, {"fields": "name,questions"})
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the form read.")
        body = _json_obj(resp)
        questions = [q for q in (_question(i) for i in _dict_items(_list_field(body, "questions"))) if q]
        return {"formName": _text(body.get("name"))[:200] or None, "questions": questions}

    def list_test_leads(self, page_token: str, form_id: str) -> List[str]:
        """The form's current test lead ids. Raises MetaLeadError (unlike
        ``test_lead_ids``, which answers None for the ingest)."""
        resp = self._get(f"{form_id}/test_leads", page_token, {"fields": "id"})
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the test lead read.")
        return [i for i in (_id_field(x, "id") for x in _dict_items(_list_field(_json_obj(resp), "data"))) if i]

    def delete_lead(self, page_token: str, lead_id: str) -> None:
        resp = self._send("DELETE", lead_id, page_token)
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the test lead delete.")

    def create_test_lead(self, page_token: str, form_id: str) -> None:
        resp = self._send("POST", f"{form_id}/test_leads", page_token)
        if resp.status_code != 200:
            raise _error(resp, "Meta refused the test lead.")
