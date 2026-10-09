"""MCP JSON-RPC dispatch (stateless Streamable HTTP). S3 serves the lifecycle
methods; ``tools/list`` and ``tools/call`` are S4."""
from typing import Any, Optional

from .. import registry
from ..models import Grant

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_VERSION = "0.1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601


def rpc_error(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def rpc_result(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def handle(product: registry.Product, grant: Grant, message: Any) -> Optional[dict]:
    """Returns the JSON-RPC response, or None for a notification (HTTP 202)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" \
            or not isinstance(message.get("method"), str):
        return rpc_error(None, INVALID_REQUEST, "Invalid request")
    method = message["method"]
    is_notification = "id" not in message
    rid = message.get("id")
    if is_notification:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return rpc_result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": f"{product.display_name} connector", "version": SERVER_VERSION},
        })
    if method == "ping":
        return rpc_result(rid, {})
    return rpc_error(rid, METHOD_NOT_FOUND, "Method not found")
