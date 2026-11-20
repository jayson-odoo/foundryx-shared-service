"""MCP JSON-RPC dispatch (stateless Streamable HTTP) - read-only tools only."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.services.throttle import ThrottleService, Throttled

from .. import registry
from ..models import Grant
from ..repositories.connector_repository import ConnectorRepository
from . import audit, product_client
from .manifest_service import ManifestService, ManifestUnavailable, visible_tools
from .oauth_service import ProductContext

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_VERSION = "0.1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_TEXT_CHARS = 120_000
MAX_ROWS = 1000
MAX_REQUEST_BODY = 1_048_576
REMOVAL_CODES = {"connector_access_removed", "user_inactive", "reconsent_required"}
AUTH_CODES_401 = {"invalid_signature", "token_expired", "replayed", "wrong_audience"}

UNREACHABLE = "The product is not reachable right now. Try again in a minute."
MISCONFIGURED = "The connection to the product is misconfigured. An admin has been notified."
NOT_RECORDED = "The call could not be recorded, so no data was returned."


def rpc_error(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def rpc_result(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def tool_error(rid: Any, message: str) -> dict:
    return rpc_result(rid, {"content": [{"type": "text", "text": message}], "isError": True})


@dataclass
class Reply:
    body: Optional[dict]
    status: int = 200
    headers: dict = field(default_factory=dict)


class McpService:
    def __init__(self, db: Session, ctx: ProductContext, grant: Grant):
        self.db = db
        self.ctx = ctx
        self.product = ctx.product
        self.grant = grant
        self.repo = ConnectorRepository(db, ctx.tenant_id)

    def handle(self, message: Any) -> Reply:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" \
                or not isinstance(message.get("method"), str):
            return Reply(rpc_error(None, INVALID_REQUEST, "Invalid request"))
        method, rid = message["method"], message.get("id")
        if "id" not in message:
            return Reply(None, 202)
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            return Reply(rpc_result(rid, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"{self.product.display_name} connector",
                               "version": SERVER_VERSION},
            }))
        if method == "ping":
            return Reply(rpc_result(rid, {}))
        if method == "tools/list":
            return Reply(self._tools_list(rid))
        if method == "tools/call":
            return self._tools_call(rid, params)
        return Reply(rpc_error(rid, METHOD_NOT_FOUND, "Method not found"))

    # --- tools/list -------------------------------------------------------------------------
    def _manifest(self) -> dict:
        return ManifestService(self.db, self.ctx.tenant_id, self.product).get()

    def _tools_list(self, rid: Any) -> dict:
        try:
            manifest = self._manifest()
        except ManifestUnavailable:
            return rpc_error(rid, INTERNAL_ERROR, UNREACHABLE)
        tools = [{
            "name": t["name"], "title": t.get("title") or t["name"],
            "description": t.get("description") or "", "inputSchema": t["input_schema"],
            "annotations": t["annotations"],
        } for t in visible_tools(manifest)]
        return rpc_result(rid, {"tools": tools})

    # --- tools/call ----------------------------------------------------------------------------
    def _tools_call(self, rid: Any, params: dict) -> Reply:
        throttle = ThrottleService(self.db)
        try:
            throttle.enforce_connector_call(grant_id=self.grant.id)
        except Throttled as exc:
            return Reply(rpc_error(rid, INTERNAL_ERROR, "Too many requests"), 429,
                         {"Retry-After": str(exc.retry_after_seconds)})
        throttle.record_connector_call(grant_id=self.grant.id)

        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(args, dict):
            return Reply(rpc_error(rid, INVALID_PARAMS, "Invalid params"))
        try:
            manifest = self._manifest()
        except ManifestUnavailable:
            return Reply(self._finish(rid, name, args, started=time.monotonic(), text=UNREACHABLE,
                                      is_error=True, status="error", error_code="upstream_unavailable"))
        tool = next((t for t in visible_tools(manifest) if t["name"] == name), None)
        if tool is None:
            return Reply(rpc_error(rid, INVALID_PARAMS, "Unknown tool"))
        schema = {**tool["input_schema"], "additionalProperties": False}
        try:
            errors = list(Draft202012Validator(schema).iter_errors(args))
        except Exception:  # noqa: BLE001 - a broken schema never sends anything
            return Reply(rpc_error(rid, INVALID_PARAMS, "Invalid params"))
        if errors:
            # Deliberately no call_log row: nothing was sent to the product.
            return Reply(rpc_error(rid, INVALID_PARAMS, f"Invalid arguments: {errors[0].message[:200]}"))
        built = self._build_request(tool, args)
        if built is None:
            return Reply(rpc_error(rid, INVALID_PARAMS, "Invalid arguments"))
        method, raw_path, query, body = built
        started = time.monotonic()
        if len(body) > MAX_REQUEST_BODY:
            return Reply(self._finish(rid, name, args, started=started,
                                      text="That request is too large.", is_error=True,
                                      status="error", error_code="request_too_large"))
        return Reply(self._forward(rid, name, args, tool, method, raw_path, query, body, started))

    def _build_request(self, tool: dict, args: dict) -> Optional[tuple[str, str, str, bytes]]:
        http = tool["http"]
        method = http["method"].upper()
        path_params = [p for p in http.get("path_params") or [] if isinstance(p, str)]
        query_params = [p for p in http.get("query_params") or [] if isinstance(p, str)]
        path = http["path_template"]
        for p in path_params:
            if p not in args:
                return None
            value = _scalar(args[p])
            if value in ("", ".", "..") or any(ord(c) < 32 or ord(c) == 127 for c in value):
                return None  # dot-segments / control chars never reach the URL
            path = path.replace("{" + p + "}", quote(value, safe=""))
        pairs = [(k, _scalar(args[k])) for k in query_params if k in args]
        query = urlencode(pairs)
        body = b""
        if method != "GET":
            rest = {k: v for k, v in args.items() if k not in path_params and k not in query_params}
            body = json.dumps(rest, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return method, path, query, body

    def _forward(self, rid, name, args, tool, method, raw_path, query, body, started) -> dict:
        g = self.grant
        consented = int(g.consented_at.timestamp())
        resp: Optional[httpx.Response] = None
        timeout = registry.tenant_config(self.db, self.ctx.tenant_id).call_timeout_seconds
        try:
            for attempt in (0, 1):
                resp = product_client.send(
                    self.product, method=method, raw_path=raw_path, query=query, body=body,
                    sub=g.product_user_id, grant_id=g.id, consented_at=consented, tool=name,
                    timeout_seconds=timeout)
                if resp.status_code != 401 or attempt == 1:
                    break
        except httpx.HTTPError:
            return self._finish(rid, name, args, started=started, text=UNREACHABLE, is_error=True,
                                status="error", error_code="upstream_unavailable")
        assert resp is not None
        code, message = _error_parts(resp)
        sc = resp.status_code
        if 200 <= sc < 300:
            return self._success(rid, name, args, resp, started)
        if sc == 401:
            return self._finish(rid, name, args, started=started, text=MISCONFIGURED, is_error=True,
                                status="error", error_code="upstream_auth", http_status=sc)
        if sc == 403 and code in REMOVAL_CODES:
            self.repo.revoke_grant(g, reason=code)
            self.db.commit()
            return self._finish(
                rid, name, args, started=started, is_error=True, status="error", error_code=code,
                http_status=sc,
                text=f"Your {self.product.display_name} access for Claude was removed. Reconnect the connector.")
        if sc in (403, 404, 422):
            return self._finish(rid, name, args, started=started, is_error=True, status="error",
                                error_code=code or "upstream_error", http_status=sc,
                                text=message or "The request was not accepted.")
        if sc == 413:
            return self._finish(rid, name, args, started=started, text="That request is too large.",
                                is_error=True, status="error", error_code="upstream_too_large",
                                http_status=sc)
        return self._finish(rid, name, args, started=started, text=UNREACHABLE, is_error=True,
                            status="error", error_code="upstream_unavailable", http_status=sc)

    def _success(self, rid, name, args, resp: httpx.Response, started) -> dict:
        try:
            data: Any = resp.json()
        except ValueError:
            data = resp.text
        rows: Optional[int] = None
        truncated = False
        if isinstance(data, list):
            rows = len(data)
            if rows > MAX_ROWS:
                truncated = True
                data = {"truncated": True, "originalRows": rows, "returnedRows": MAX_ROWS,
                        "data": data[:MAX_ROWS]}
        elif isinstance(data, dict) and isinstance(data.get("rows"), list):
            rows = len(data["rows"])
            if rows > MAX_ROWS:
                truncated = True
                data = {**data, "rows": data["rows"][:MAX_ROWS], "truncated": True,
                        "originalRows": rows, "returnedRows": MAX_ROWS}
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        original_chars = len(resp.text)  # characters, not bytes
        if len(text) > MAX_TEXT_CHARS:
            truncated = True
            cut = MAX_TEXT_CHARS
            while True:
                out = json.dumps({"truncated": True, "originalChars": original_chars,
                                  "text": text[:cut]}, separators=(",", ":"), ensure_ascii=False)
                if len(out) <= MAX_TEXT_CHARS + 4000 or cut < 1000:
                    break
                cut //= 2
            text = out
        return self._finish(rid, name, args, started=started, text=text, is_error=False, status="ok",
                            http_status=resp.status_code, rows=rows, chars=len(text),
                            truncated=truncated)

    def _finish(self, rid, name, args, *, started: float, text: str, is_error: bool, status: str,
                error_code: Optional[str] = None, http_status: Optional[int] = None,
                rows: Optional[int] = None, chars: Optional[int] = None,
                truncated: bool = False) -> dict:
        """Audit FIRST (committed), only then hand the result back - fail closed."""
        try:
            audit.write_call_log(
                self.db, grant=self.grant, tool=name, args=args, status=status,
                duration_ms=int((time.monotonic() - started) * 1000), rows=rows,
                chars=chars if chars is not None else len(text), error_code=error_code,
                http_status=http_status, truncated=truncated)
        except Exception:  # noqa: BLE001
            self.db.rollback()
            return tool_error(rid, NOT_RECORDED)
        result: dict = {"content": [{"type": "text", "text": text}]}
        if is_error:
            result["isError"] = True
        return rpc_result(rid, result)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def _error_parts(resp: httpx.Response) -> tuple[Optional[str], Optional[str]]:
    try:
        err = resp.json().get("error")
    except (ValueError, AttributeError):
        return None, None
    if isinstance(err, dict):
        code, msg = err.get("code"), err.get("message")
        return (code if isinstance(code, str) else None,
                msg[:500] if isinstance(msg, str) else None)
    return None, None
