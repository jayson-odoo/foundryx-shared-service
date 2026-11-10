# Plan 38 gap 5 acceptance criteria: `POST /api/v1/omnichannel/contacts/{identifier}/read`

A consumer that never logs in to SS needs its staff opening a conversation to show as read: unread resets, and the customer sees blue ticks on WhatsApp. Today nothing sends a read receipt to the provider, and only the internal thread read resets unread.

## Rules

| AC | Rule |
|---|---|
| AC-38-50 | `POST /api/v1/omnichannel/contacts/{identifier}/read` under the API key takes no body and uses the `{identifier}` convention of the other contact routes. Tenant and workspace come only from the key. An unknown contact, or one in another workspace or tenant, gets the same `404 contact_not_found` as the other contact routes. A missing or invalid key, or an inactive module, gets the same error as the other gateway routes |
| AC-38-51 | A found contact always answers `200` with `{"contactId": "<id>", "receipts": [...]}`. Afterwards `unreadCount` on `GET /contacts/{identifier}` reads `0`, even when every receipt failed, and whatever shape a message's stored metadata has. A customer message arriving later counts as unread again |
| AC-38-52 | `receipts` has one item per channel the contact has written in on, each exactly `{"channelId", "messageId", "status"}`. `messageId` is the SS message id, the same `id` as on `MessageItem`. The target on each channel is the customer's latest message there that has a provider id and was not imported. On a `created_at` tie the greater id wins, as in the repository's thread order. Agent, system and note rows are never a target. A contact with no such message answers `"receipts": []` |
| AC-38-53 | On a WhatsApp channel the provider call is `POST /{phone_number_id}/messages` with exactly `messaging_product: "whatsapp"`, `status: "read"`, `message_id: <the target's provider id>`, using that channel's own phone number id and credentials, never the workspace default channel's. A provider `200` with `success: true` gives status `sent`. Any other `200` body counts as a refusal under AC-38-55 |
| AC-38-54 | A second call with no new customer message makes no provider call and answers `already_sent` for that channel. A new customer message makes a new provider call on the new message. Channels are independent. The stored marker appears in no read shape or webhook |
| AC-38-55 | A provider refusal, a provider that cannot be reached, unreadable channel credentials or an unexpected adapter error gives status `failed` on that channel only: the route still answers `200`, other channels are still attempted, no marker is stored so the next call tries again, and no provider text reaches the response. If the provider accepted but the marker cannot be stored, the status stays `sent`, other channels are still attempted, and the next call sends again. A failure closing the connection after the provider accepted changes nothing: `sent`, marker stored, no error text recorded. An unexpected adapter error and a budget skip each log a warning holding only the channel id and the error class |
| AC-38-56 | A paused or disconnected channel in the key's workspace answers `channel_unavailable` with no provider call, even when its latest message already has a marker. So does a WhatsApp channel whose phone number id is empty or is anything but letters, digits, `_` and `-`. A channel row outside the key's tenant or workspace is never used for a provider call and is left out of `receipts` |
| AC-38-57 | A Messenger, Instagram or web chat channel answers `not_supported` with no provider call. A channel with dev credentials, or with the provider app unconfigured, makes no network call and answers `sent`, as sends do on such channels |
| AC-38-58 | The unread reset is committed before the first provider call, and no database transaction stays open across a provider call |
| AC-38-59 | Each provider call is recorded in the channel's activity log the way a send is, with the target's provider id as its reference and the provider's HTTP status. On a failure the record holds only the HTTP status, the provider's numeric error code when it sends one, and fixed wording. It never holds the provider's error text or a transport error's text, so no token can reach it in any form |
| AC-38-60 | The route creates no message row and fires no webhook, workflow trigger or `message.status` event |
| AC-38-61 | Every query is tenant scoped. A foreign tenant's rows with the same contact id, workspace id or channel id neither change the answer nor receive a provider call |
| AC-38-62 | `documentation/omnichannel/consumer-integration-guide.md` documents the route in section 6a and the appendix index, with every `status` value and what to do about it (`failed` is safe to call again but can repeat on every call, so do not alert or loop on it; `channel_unavailable` needs nothing unless that channel is still in use), states that only this route sends a read receipt and that it can take up to 30 seconds, and has a changelog row |
| AC-38-63 | Each provider call has its own limit: connect 3 s, read and write 5 s. The request has an overall budget of 12 s: a channel that still needs a provider call after the budget has gone answers `failed` with no call. A channel that needs no call keeps its answer, such as `already_sent` |

## Build notes

Paths are under `service_backend/modules/omnichannel/`.

- Route in `routers/api_v1.py` beside `add_comment`, HTTP and Pydantic only. Service method in `services/public_gateway_service.py`, resolving the contact through `_resolve_contact`. Queries live in `repositories/contact_repository.py`.
- `mark_read` on the adapter in `adapters/whatsapp_cloud.py`, wrapped in `_graph_call` with its own label, and following `send`'s dev and unconfigured handling. Its response has no `messages` array, so it does not reuse `_send_impl`.
- The adapter is built with `build_meta_recorder`, as at `services/message_service.py:830`.
- Marker: a key in the target message's `metadata_json`, reassigned as a fresh dict. No migration, so no backfill: old messages simply have no marker.
- Latest message per channel must be one bounded query, not a load of the contact's history.
- Inbound reactions never become message rows (`adapters/whatsapp_cloud.py:668`), so they need no exclusion.
- The overall budget is `READ_RECEIPT_BUDGET_SECONDS` in `services/public_gateway_service.py`, measured with `time.monotonic()` and checked before each provider call.

## Decisions

- Receipts go per channel, because a customer can write to two numbers in one workspace, and a receipt on one does not tick the other.
- Failure answers `200` per channel: unread is SS's own state and has already changed, so a whole-request error would misreport it.
- Messenger and Instagram read receipts are out of scope, BL-SS-320. The partner inbox is WhatsApp only.
- The internal inbox keeps resetting unread without a receipt. Changing that is a product decision for SS staff, not part of this gap.
- Receipts run inside the request, so the consumer gets a per-channel answer. Unlike sends they do not go through the queue, which is why AC-38-63 limits them.
- A provider refusal stores no permanent marker: a 4xx also covers a recoverable case such as an expired token.
- Meta's [mark as read guide](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/mark-message-as-read) documents the request body, the `{"success": true}` response and marking within 30 days of receipt. In a one-to-one chat a receipt also covers earlier messages, which is why only the latest message per channel is targeted.

Documented only, not yet confirmed by a live call: plan 38 Phase 3 covers that, and it waits on the owner's environment decision.
