"""Instagram DM adapter - plan 32 / A7a.

Subclasses `MessengerAdapter` (D-A7-14): Instagram v1 is the Facebook-Page-
linked topology only - one OAuth, one page access token, the SAME send/webhook
mechanics as Messenger, just a different `object` value and a different linked
account. Slice S1 registers the type (AC-CHN-15: `get_adapter("INSTAGRAM")`
must resolve, not raise) by inheriting Messenger's inbound parsing verbatim;
the Instagram-specific overrides (IG-only inbound kinds as `UNSUPPORTED`
placeholders - story_reply/story_mention/share, D-A7-14 - and page-linked IG
account listing for the connect flow) land in plan 32 S4, on this same file,
never a copy of Messenger's.

Source: Instagram messaging webhooks (object `instagram`, IGSID):
https://developers.facebook.com/docs/messenger-platform/instagram/features/webhook
"""
from .messenger import MessengerAdapter


class InstagramAdapter(MessengerAdapter):
    channel_type = "INSTAGRAM"
