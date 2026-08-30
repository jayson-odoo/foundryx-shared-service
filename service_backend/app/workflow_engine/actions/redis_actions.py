"""Generic Redis workflow action (sprint-4/19 S3, AC-SAR-43..48).

Builders address LOGICAL keys. Every command maps the logical key under a
tenant-managed physical namespace, so a workflow can never reach the Celery
broker, websocket rooms, the serialized-run leases, or another tenant's data.
The physical prefix is an internal detail: it never appears in node config,
node output, or error text (run logs stay redacted).
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict, Iterator, Optional

from sqlalchemy.orm import Session

from app.workflow_engine.context import render_field


class ActionError(Exception):
    pass


OPERATIONS = ("get", "set", "delete", "increment", "list_push", "list_pop", "list_length")
LIST_ENDS = ("left", "right")

# Root of every physical key the platform writes on behalf of a workflow. A
# logical key is rejected when it tries to spell an internal prefix itself.
_DATA_ROOT = "foundryx:workflow:data"
_RESERVED_LOGICAL_PREFIXES = ("foundryx:",)
MAX_LOGICAL_KEY_LENGTH = 512
MAX_VALUE_LENGTH = 64 * 1024

_client_override: Any = None


def _default_client() -> Any:
    from redis import Redis

    from app.config import settings

    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_workflow_data_client() -> Any:
    """Production client for workflow data. Tests swap it via
    :func:`use_workflow_redis_client` (the injected seam of AC-SAR-48)."""
    return _client_override if _client_override is not None else _default_client()


@contextlib.contextmanager
def use_workflow_redis_client(client: Any) -> Iterator[None]:
    global _client_override
    previous = _client_override
    _client_override = client
    try:
        yield
    finally:
        _client_override = previous


def physical_key(tenant_id: str, logical_key: str) -> str:
    return f"{_DATA_ROOT}:{tenant_id}:{logical_key}"


def validate_logical_key(logical_key: Any) -> str:
    if not isinstance(logical_key, str) or not logical_key.strip():
        raise ActionError("Redis: a key is required.")
    key = logical_key.strip()
    if len(key) > MAX_LOGICAL_KEY_LENGTH:
        raise ActionError(f"Redis: the key exceeds {MAX_LOGICAL_KEY_LENGTH} characters.")
    if any(ch in key for ch in "\r\n\x00"):
        raise ActionError("Redis: the key contains an invalid character.")
    lowered = key.lower()
    if any(lowered.startswith(prefix) for prefix in _RESERVED_LOGICAL_PREFIXES):
        raise ActionError("Redis: that key prefix is reserved.")
    return key


class WorkflowRedisService:
    """Tenant-namespaced commands over platform Redis. The physical prefix
    never leaves this class."""

    def __init__(self, tenant_id: str, client: Any = None):
        if not tenant_id:
            raise ActionError("Redis: tenant scope is required.")
        self.tenant_id = tenant_id
        self.client = client if client is not None else get_workflow_data_client()

    def _k(self, logical_key: str) -> str:
        return physical_key(self.tenant_id, validate_logical_key(logical_key))

    def get(self, key: str) -> Optional[str]:
        return self.client.get(self._k(key))

    def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
        if ttl_seconds is not None:
            return bool(self.client.set(self._k(key), value, ex=ttl_seconds))
        return bool(self.client.set(self._k(key), value))

    def delete(self, key: str) -> bool:
        return bool(self.client.delete(self._k(key)))

    def increment(self, key: str, amount: int) -> int:
        return int(self.client.incrby(self._k(key), amount))

    def list_push(self, key: str, value: str, end: str) -> int:
        if end == "left":
            return int(self.client.lpush(self._k(key), value))
        return int(self.client.rpush(self._k(key), value))

    def list_pop(self, key: str, end: str) -> Optional[str]:
        if end == "left":
            return self.client.lpop(self._k(key))
        return self.client.rpop(self._k(key))

    def list_length(self, key: str) -> int:
        return int(self.client.llen(self._k(key)))


def _int_field(raw: str, label: str, *, minimum: Optional[int] = None) -> int:
    text = raw.strip()
    try:
        number = int(text)
    except ValueError as exc:
        raise ActionError(f"Redis: {label} must be a whole number.") from exc
    if minimum is not None and number < minimum:
        raise ActionError(f"Redis: {label} must be at least {minimum}.")
    return number


def literal_config_issues(config: Dict[str, Any], label: str = "Redis") -> list[str]:
    """Publish-time checks on LITERAL values (merge expressions resolve at run
    time and are validated there). Mirrors the frontend's checks."""
    issues: list[str] = []
    op = config.get("operation")
    if op not in OPERATIONS:
        issues.append(f'{label}: "Operation" must be one of the supported commands.')
        return issues
    key = config.get("key")
    if isinstance(key, str) and key.strip() and "{{" not in key:
        try:
            validate_logical_key(key)
        except ActionError as exc:
            issues.append(f"{label}: {str(exc).replace('Redis: ', '')}")
    end = config.get("end")
    if op in ("list_push", "list_pop") and end not in (None, "") and end not in LIST_ENDS:
        # A missing end defaults to Right at run time; only a wrong value fails.
        issues.append(f'{label}: "List end" must be Left or Right.')
    ttl = config.get("ttlSeconds")
    if op == "set" and isinstance(ttl, str) and ttl.strip() and "{{" not in ttl:
        if not ttl.strip().isdigit() or int(ttl.strip()) < 1:
            issues.append(f'{label}: "TTL seconds" must be a positive whole number.')
    amount = config.get("amount")
    if op == "increment" and isinstance(amount, str) and amount.strip() and "{{" not in amount:
        stripped = amount.strip()
        if not (stripped.lstrip("-").isdigit()):
            issues.append(f'{label}: "Amount" must be a whole number.')
    return issues


def redis_command(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """Executor for ``redis.command``. Any store failure fails ONLY this node
    (the executor skips downstream); nothing here touches Agent state or the
    serialized-run leases, which live under different prefixes."""
    del db  # the data store is Redis; the session is untouched
    op = config.get("operation")
    if op not in OPERATIONS:
        raise ActionError("Redis: choose a supported operation.")
    key = render_field(config.get("key"), ctx)
    try:
        service = WorkflowRedisService(tenant_id)
        if op == "get":
            return {"value": service.get(key)}
        if op == "set":
            value = render_field(config.get("value"), ctx)
            if len(value) > MAX_VALUE_LENGTH:
                raise ActionError("Redis: the value is too large.")
            ttl_raw = config.get("ttlSeconds")
            ttl: Optional[int] = None
            if isinstance(ttl_raw, str) and ttl_raw.strip():
                ttl = _int_field(render_field(ttl_raw, ctx), "TTL seconds", minimum=1)
            elif isinstance(ttl_raw, (int, float)) and ttl_raw:
                ttl = _int_field(str(int(ttl_raw)), "TTL seconds", minimum=1)
            return {"stored": service.set(key, value, ttl)}
        if op == "delete":
            return {"deleted": service.delete(key)}
        if op == "increment":
            amount_raw = config.get("amount")
            amount = 1
            if isinstance(amount_raw, str) and amount_raw.strip():
                amount = _int_field(render_field(amount_raw, ctx), "Amount")
            elif isinstance(amount_raw, (int, float)):
                amount = int(amount_raw)
            return {"value": service.increment(key, amount)}
        end = config.get("end") or "right"
        if end not in LIST_ENDS:
            raise ActionError("Redis: list end must be Left or Right.")
        if op == "list_push":
            value = render_field(config.get("value"), ctx)
            if len(value) > MAX_VALUE_LENGTH:
                raise ActionError("Redis: the value is too large.")
            return {"length": service.list_push(key, value, end)}
        if op == "list_pop":
            return {"value": service.list_pop(key, end)}
        return {"length": service.list_length(key)}
    except ActionError:
        raise
    except Exception as exc:  # noqa: BLE001 - connection/response errors
        # Never echo the physical key or connection details into the run log.
        name = type(exc).__name__
        if "ResponseError" in name or "DataError" in name:
            raise ActionError("Redis: the command is not valid for the stored value.") from exc
        raise ActionError("Redis: the workflow data store is unavailable.") from exc


__all__ = [
    "ActionError",
    "LIST_ENDS",
    "OPERATIONS",
    "WorkflowRedisService",
    "get_workflow_data_client",
    "literal_config_issues",
    "physical_key",
    "redis_command",
    "use_workflow_redis_client",
    "validate_logical_key",
]
