# Plan 38 gap 4: `replyToMessageId` on the public send

UAC: `38-gap4-reply-to-acceptance-criteria.md`. Size M: public contract change on an API-key route, no migration, no screen. Branch `crew/ss-fuji-gap4`.

## Design

Paths under `service_backend/modules/omnichannel/`.

```text
PublicSendRequest.replyToMessageId: Optional[str]        schemas.py (class PublicSendRequest)

public_gateway_service.send -> _do_send
  channel resolved as today (channel_required, no_active_channel unchanged)
  replyToMessageId set:
    type == reaction                -> 422 invalid_request, nothing sent
    quoted = message by id, tenant from the key, contact from `to`
      missing / other contact / SYSTEM  -> the existing "not found" refusal (same status, code, body)
      quoted.channel_id set and != resolved channel -> 422 reply_channel_mismatch
  pass reply_to_message_id to
    messages.send_message      (text, template)
    messages.send_media        (_send_media)
    messages.send_interactive / send_location / send_contacts  (_send_structured)
```

- The quoted row is resolved through `MessageService._reply_metadata` (`services/message_service.py:264`), which already checks tenant, contact and internal notes; the gateway adds only the channel comparison, so the inbox path is unchanged.
- The multipart route (`routers/api_v1.py`, about :95-135) does not build a `PublicSendRequest`: it reads `type`, `to`, `channelId` and `media` from the `payload` JSON one by one and calls the upload send. It needs `replyToMessageId` read the same way and passed through, with the same checks as the JSON path (one shared helper in the gateway, not two copies).
- Idempotency is keyed by the key alone (`public_gateway_service.py` about :935-960: reserve, replay the stored id, release on any exception). A refusal raised before the send therefore frees the key; a replay ignores the new body, as on every send today (AC-38-75).
- Error envelope and codes follow the gateway's existing table; `reply_channel_mismatch` is the only new code.

## Order

1. Tester: red tests for AC-38-70..76 in `service_backend/tests/` (new file `test_omnichannel_public_reply_to.py`), plus a guide test for AC-38-77 alongside the existing guide tests.
2. Coder: schema field, gateway checks and pass-through until green.
3. Guide-writer: section 4, 4.3, error rows, changelog.
4. Kill test, reviewer + security-reviewer in parallel (API-key route), CI, Merge-ready.

## Out of scope

Live Meta acceptance of a quote on each message type (Phase 3).
