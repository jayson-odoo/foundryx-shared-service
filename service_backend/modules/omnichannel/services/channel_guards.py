"""ONE shared guard for WhatsApp-only surfaces (plan 32 / A7a, D-A7-17,
AC-CHN-37): message templates and the WhatsApp Business Profile mirror are
Meta WABA concepts with no Messenger/Instagram equivalent - a `FACEBOOK` or
`INSTAGRAM` channel refuses these routes with a typed 409 rather than
attempting a Graph call that can only fail. Every service that owns one of
these routes calls `assert_whatsapp` at its single channel-resolution point
(`TemplateManagementService._channel`, `ChannelProfileService._channel`) so
the refusal is enforced once, not re-checked per method.
"""
from ..models import Channel


class ChannelTypeUnsupported(Exception):
    """Typed 409 reason `channel_type_unsupported` (plan §5.1) - raised when a
    WhatsApp-only operation is attempted against a non-WhatsApp channel."""

    def __init__(self, reason: str = "channel_type_unsupported"):
        super().__init__(reason)
        self.reason = reason


def assert_whatsapp(channel: Channel) -> None:
    if channel.channel_type != "WHATSAPP":
        raise ChannelTypeUnsupported()
