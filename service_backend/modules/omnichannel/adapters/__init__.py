"""Channel adapter REGISTRY (plan 32 / A7a, D-A7-9).

`get_adapter(channel_type)` resolves the concrete adapter for a channel type -
`WHATSAPP` | `FACEBOOK` | `INSTAGRAM` | `WEBCHAT` (plan 34 / A7b, AC-WEB-12; an
unknown type still raises). `adapters.whatsapp_cloud.get_adapter` stays as a
thin re-export: eight existing modules import `get_adapter` off
`whatsapp_cloud` directly, and rewriting those import sites inside a slice
that is ALREADY refactoring the send path is pure risk for zero behaviour -
the import sweep is BL-SS-115.
"""
from typing import Optional

import httpx

from .instagram import InstagramAdapter
from .messenger import MessengerAdapter
from .meta_graph import GraphRecorder
from .webchat import WebChatAdapter
from .whatsapp_cloud import WhatsAppCloudAdapter

ADAPTERS = {
    "WHATSAPP": WhatsAppCloudAdapter,
    "FACEBOOK": MessengerAdapter,
    "INSTAGRAM": InstagramAdapter,
    "WEBCHAT": WebChatAdapter,
}


def get_adapter(
    channel_type: str = "WHATSAPP",
    client: Optional[httpx.Client] = None,
    recorder: Optional[GraphRecorder] = None,
):
    """Resolve a channel adapter by type. An optional ``recorder`` (owned by
    the service layer) turns on outbound-Meta activity logging - see
    ``build_meta_recorder`` (sprint-4/12 Slice 2)."""
    cls = ADAPTERS.get(channel_type)
    if cls is None:
        raise ValueError(f"Unsupported channel type: {channel_type}")
    return cls(client=client, recorder=recorder)
