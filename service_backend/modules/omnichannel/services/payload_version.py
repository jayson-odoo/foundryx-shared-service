"""Consumer payload versions: one seam for every additive change to an existing
webhook body or API-key response.

A consumer that does nothing gets version 1, today's exact bytes, forever. A
webhook endpoint opts in with its stored ``payload_version``; an API-key request
opts in with the ``X-Fx-Api-Version`` header. A new key on an existing shape is
served only at the version that introduced it.

How a later change uses it:

1. Add the field to the Pydantic shape (optional, default ``None``) and make the
   shape inherit ``VersionedPayload`` (first base, before ``ApiModel``).
2. Register the wire key below in ``GATED_KEYS`` under the shape's class name.
   Subclasses of a registered shape are covered too.
3. Nothing else: every dump of that shape strips the key unless it runs inside
   ``serializing(version)`` with a version that shows it. Webhook fan-out builds
   each endpoint's body inside ``serializing(<endpoint version>)``; API routes
   answer with ``versioned(...)`` in ``routers/api_v1.py``. Any other dump
   (dashboard routes, realtime events, logs) is version 1.

For a hand-built dict (no Pydantic shape) use ``visible`` or ``strip`` with a
shape name of your choosing registered here.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

V1 = 1
V2 = 2
LATEST = V2
VERSIONS = (V1, V2)

# THE registry: shape (class name) -> {wire key: first version that shows it}.
GATED_KEYS: Dict[str, Dict[str, int]] = {
    "WebhookEndpointItem": {"payloadVersion": V2},
    # Track A S1: messaging window state.
    "ThreadItem": {"windowOpen": V2, "allowedSendTypes": V2, "windowReason": V2, "windows": V2},
    "PublicMessageListResponse": {"window": V2},
    # Track A S3: who sent a message.
    "MessageItem": {"sender": V2},
    # Track A S4: template header/button shape.
    "PublicTemplateItem": {"headerFormat": V2, "headerVariableCount": V2, "buttonVariableCount": V2},
    # Track A S9: channel connection state.
    "PublicChannelItem": {"connectionState": V2},
    # Track A S2: hand-built `details` on the public window refusals (409).
    "WindowRefusal": {"details": V2},
}

# Registry names above that are not Pydantic shapes: hand-built dicts read with
# ``visible`` / ``strip``.
HAND_BUILT = frozenset({"WindowRefusal"})

_current: ContextVar[int] = ContextVar("omnichannel_payload_version", default=V1)


def current() -> int:
    """The version being serialized now; version 1 outside ``serializing``."""
    return _current.get()


@contextmanager
def serializing(version: int) -> Iterator[None]:
    """Serialize shapes at ``version`` inside the block."""
    token = _current.set(version)
    try:
        yield
    finally:
        _current.reset(token)


def is_known(version: Any) -> bool:
    return type(version) is int and version in VERSIONS


def effective(stored: Optional[int]) -> int:
    """A stored endpoint version; NULL means version 1."""
    return stored or V1


def visible(shape: str, key: str, version: int) -> bool:
    """Is ``key`` of ``shape`` shown at ``version``? Unregistered keys always are."""
    return version >= GATED_KEYS.get(shape, {}).get(key, V1)


def strip(shape: str, payload: Dict[str, Any], version: int) -> Dict[str, Any]:
    """``payload`` without the keys of ``shape`` hidden at ``version``; key order kept."""
    gated = GATED_KEYS.get(shape)
    if not gated:
        return payload
    return {k: v for k, v in payload.items() if version >= gated.get(k, V1)}


class VersionedPayload(BaseModel):
    """Base for a shape with keys in ``GATED_KEYS``: every dump drops the keys
    the version being serialized does not show."""

    @model_serializer(mode="wrap")
    def _strip_gated_keys(self, handler: SerializerFunctionWrapHandler):
        data = handler(self)
        if isinstance(data, dict):
            version = current()
            for cls in type(self).__mro__:
                data = strip(cls.__name__, data, version)
        return data
