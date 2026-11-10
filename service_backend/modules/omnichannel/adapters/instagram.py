"""Instagram DM adapter - plan 32 / A7a, Slice S4 (AC-CHN-40..45).

Subclasses `MessengerAdapter` (D-A7-14): Instagram v1 is the Facebook-Page-
linked topology only - one OAuth, one page access token, the SAME send/webhook
mechanics as Messenger, just a different `object` value and a different linked
account. `channel_type` is the ONLY override needed for onboarding, outbound
send, addressing and connection testing - `MessengerAdapter.list_pages`
already returns each page's linked `instagram_business_account` and
`meta_connect_service` already resolves it (plan 32 S3), `channel_addressing`
already sends to `external_user_id`/`external_account_id` for both types (plan
32 S2), and `messaging_policy` already carries an independent INSTAGRAM policy
+ capability row (plan 32 S2).

The ONLY thing Instagram's inbound parsing does differently (AC-CHN-40) is a
handful of Instagram-only message shapes Messenger never sends: a reply to a
story, a story mention, a shared post/media, an unsent ("deleted") message and
an explicitly-unsupported message. None of those carry a regular text/
attachment/quick_reply/postback shape, so `_parse_one` checks for them FIRST
and falls through to `MessengerAdapter._parse_one` (text, image/video/audio,
quick replies, postbacks, delivery/read receipts, reactions - all reused
verbatim, never copied) for everything else, including a plain echo drop
(D-A7-23 applies identically on Instagram).

Source (object `instagram`, IGSID, entry[].id = the Instagram professional
account id, the five payload shapes below):
https://developers.facebook.com/docs/messenger-platform/instagram/features/webhook
"""
import logging
from typing import Any, Dict, Optional

from .messenger import MessengerAdapter

logger = logging.getLogger(__name__)

# Instagram-only `message.attachments[].type` values (AC-CHN-41) - neither is
# in `MessengerAdapter._ATTACHMENT_TYPES`, so the base parser would already
# fall back to an `UNSUPPORTED` placeholder for them; this module intercepts
# them FIRST only to preserve a story/permalink reference in `payload`
# (Meta's docs: "only the URL for the shared media or post is included").
_IG_ONLY_ATTACHMENT_KINDS = {"story_mention", "share"}


class InstagramAdapter(MessengerAdapter):
    channel_type = "INSTAGRAM"

    def _parse_one(self, item: Dict[str, Any], page_id: Optional[str]) -> Optional[Dict[str, Any]]:
        message = item.get("message")
        if isinstance(message, dict) and not message.get("is_echo"):
            placeholder = self._parse_ig_only_kind(item, message)
            if placeholder is not None:
                return placeholder
        return super()._parse_one(item, page_id)

    def _parse_ig_only_kind(
        self, item: Dict[str, Any], message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Recognize the Instagram-only inbound shapes this slice does not
        model as first-class message types (AC-CHN-41: story reply, story
        mention, media share, unsend, an explicitly-unsupported message) and
        return the house `UNSUPPORTED` placeholder with the payload preserved
        - never `None` for a recognized shape, so the pipeline never drops
        it; ``None`` when the message is none of these (the caller falls
        through to the inherited Messenger parsing)."""
        sender = (item.get("sender") or {}).get("id")
        if not sender:
            return None
        mid = message.get("mid")
        timestamp = item.get("timestamp")

        if message.get("is_deleted"):
            logger.info("Instagram message unsend (is_deleted) from %s stored as placeholder", sender)
            return self._ig_placeholder(sender, mid, timestamp, "unsend", {"kind": "unsend"})

        if message.get("is_unsupported"):
            logger.info("Instagram unsupported message from %s stored as placeholder", sender)
            return self._ig_placeholder(
                sender, mid, timestamp, "is_unsupported", {"kind": "unsupported"}
            )

        story = (message.get("reply_to") or {}).get("story")
        if isinstance(story, dict):
            logger.info("Instagram story reply from %s stored as placeholder", sender)
            return self._ig_placeholder(
                sender, mid, timestamp, "story_reply",
                {"kind": "story_reply", "storyId": story.get("id"), "storyUrl": story.get("url")},
                body=message.get("text"),
            )

        for att in message.get("attachments") or []:
            att_type = (att.get("type") or "").lower()
            if att_type in _IG_ONLY_ATTACHMENT_KINDS:
                url = (att.get("payload") or {}).get("url")
                logger.info("Instagram %s from %s stored as placeholder", att_type, sender)
                return self._ig_placeholder(
                    sender, mid, timestamp, att_type, {"kind": att_type, "url": url}
                )

        return None

    @staticmethod
    def _ig_placeholder(
        sender: str,
        mid: Optional[str],
        timestamp: Any,
        original_type: str,
        payload: Dict[str, Any],
        *,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """The house `UNSUPPORTED` placeholder shape (AC-CHN-41) - stored,
        logged, never dropped and never raised. ``payload`` carries whatever
        reference Meta gave us (story id/url, shared-post url) so the row is
        forensically useful even though this slice renders it as a generic
        placeholder bubble."""
        return {
            "kind": "message",
            "external_message_id": mid,
            "from": sender,
            "profile_name": None,
            "message_type": "UNSUPPORTED",
            "original_type": original_type,
            "body": body,
            "payload": payload,
            "timestamp": timestamp,
        }
