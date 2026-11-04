# Plan 38 gap 4 acceptance criteria: `replyToMessageId` on `POST /messages`

A consumer's staff can quote a customer message when replying, as agents can in the inbox. The send path already supports a quoted reply; this gap passes the field through the public gateway.

## Rules

| AC | Rule |
|---|---|
| AC-38-70 | [BE] `POST /api/v1/omnichannel/messages` takes an optional `replyToMessageId` in the JSON body and in the multipart `payload`, holding the message `id` from `MessageItem`. Without it every send behaves exactly as today |
| AC-38-71 | [BE] It works on `text`, `template`, the media types, `interactive`, `location` and `contacts`. On `reaction`, which already targets a message, it answers `422 invalid_request` and nothing is sent |
| AC-38-72 | [BE] The created message shows `replyTo` on the history read and in the `?format=rio` shape, as an inbox reply does. On WhatsApp the provider request carries `context.message_id` set to the quoted message's provider id. A quoted message with no provider id sends without a quote and still shows `replyTo` |
| AC-38-73 | [BE] An unknown id, another contact's message, another workspace's or tenant's message, and an internal note all answer the same status, code and body, and nothing is sent: no message row, no queued send. Tenant and contact come from the key and the `to` value, never from the quoted row |
| AC-38-74 | [BE] The send's channel is resolved first, exactly as today (including `422 channel_required` when the default is a guess, AC-38-89). A quoted message on a different channel from the resolved one answers `422 reply_channel_mismatch`, and nothing is sent. A quoted message with no channel is allowed. The send never moves to the quoted message's channel by itself |
| AC-38-75 | [BE] An `Idempotency-Key` replay behaves as on other sends: the key alone identifies the send, so a second request with the same key replays the first result (same message id, `idempotencyReplay: true`) and sends nothing, whatever its `replyToMessageId`. A refused send (AC-38-71, 73, 74) frees the key, so a corrected retry with the same key sends |
| AC-38-76 | [BE] `message.outbound` and `message.status` fire as on any send, and the new field changes neither envelope shape |
| AC-38-77 | [DOC] `documentation/omnichannel/consumer-integration-guide.md` documents the field in section 4, including the multipart `payload` in section 4.3, every rule above, the two error rows, and a changelog row |

No migration, no permission change, no screen change.

## Decisions

- The channel mismatch has its own error, not the "not found" one: the row is the contact's own message, and the consumer needs to know that passing the quoted message's `channelId` fixes it.
- A mismatch is refused rather than moving the send to the quoted message's channel: choosing a number for the consumer is an ambiguous action.

Not verified against live Meta here: whether Meta accepts a quote on every message type, templates in particular. A refusal arrives as `message.status` `FAILED`. Plan 38 Phase 3 covers it.
