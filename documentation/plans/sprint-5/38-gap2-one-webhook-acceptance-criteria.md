# Plan 38 gap 2 acceptance criteria: one webhook for all channels, and naming the channel on send

Plan: `38-gap2-one-webhook.md`.

## Journey

A consumer's system holds one API key for a workspace with several WhatsApp numbers. Nobody on its side logs in to SS.

1. It calls `GET /channels` and learns the numbers and their ids.
2. It registers one URL with `POST /webhooks`. It does not choose a number, because that URL covers them all.
3. Events from any number arrive at that URL. Each says which number it belongs to in `channelId`.
4. It sends with `channelId` set to the number it wants. If it leaves `channelId` out while the workspace has several numbers, it gets `422 channel_required` at once, nothing goes out, and it can retry with the same Idempotency-Key.
5. A staff user in SS opens any of those channels' Webhooks tab and sees the endpoint labelled "All channels", and can pause or delete it there.

A workspace with one number sees no change on send. Its new registrations also cover any number connected later.

## What "a real guess" means

With no `channelId`, the default is a guess when the group it picks from has more than one channel: more than one active WhatsApp channel, or no active WhatsApp channel and more than one other active channel. Active means `is_active` and not trashed. One active WhatsApp channel plus any number of other channels is not a guess: the WhatsApp channel is used, as the guide promises.

## Registration

| AC | Rule |
|---|---|
| AC-38-80 | [BE] `POST /api/v1/omnichannel/webhooks` creates an endpoint with `channelId: null`, tenant and workspace taken only from the key. The request has no channel field; a `channelId` sent in the body does not bind the endpoint to a channel. A workspace with no active channel gets `409 no_active_channel` as today, nothing saved, so that staff can always see the row on a channel's tab |
| AC-38-81 | [BE] `GET /webhooks` returns such an endpoint with `channelId: null`. PATCH, rotate, enable, disable and DELETE work on it, and each answers 404 for an endpoint of another workspace or tenant, as for a per-channel endpoint |
| AC-38-82 | [BE] A workspace holds at most 10 all-channels endpoints. The 11th answers `422 invalid_request`, nothing saved. Per-channel endpoints do not count toward this limit, and all-channels endpoints do not count toward a channel's limit of 10. Each limit holds under parallel registration: the URL is checked before the count, and the count and insert run under a row lock |
| AC-38-83 | [BE] `POST /omnichannel/channels/{id}/webhooks` still creates a per-channel endpoint. Existing endpoints keep their `channelId`, events, secret and status through the migration |

## Delivery

| AC | Rule |
|---|---|
| AC-38-84 | [BE] An event on either of two WhatsApp channels in a workspace reaches a subscribed all-channels endpoint exactly once, and the envelope's `channelId` is the channel the event happened on. Covers `message.inbound`, `message.outbound`, `message.status` and `message.reaction`, each through its real producer |
| AC-38-85 | [BE] A per-channel endpoint still receives only its own channel's events. An all-channels endpoint and a per-channel endpoint with the same URL each get their own delivery row for one event |
| AC-38-86 | [BE] An all-channels endpoint receives nothing from another tenant with the same workspace id, or from another workspace in the same tenant. A `DISABLED` or `AUTO_DISABLED` one receives nothing, nor does one not subscribed to the event |
| AC-38-87 | [BE] Delivery of an all-channels endpoint runs the real path: signed as any other endpoint, retried on failure, counted toward auto-disable, and listed in its delivery log |
| AC-38-88 | [BE] `contact.updated`: one change gives an all-channels endpoint one event. Envelope `channelId` is the contact's latest channel, or null when the contact has never messaged. A per-channel endpoint behaves as today: only the latest channel's endpoints receive it, and none when the contact has never messaged. A latest channel in another workspace counts as no channel. A failure here never reaches the caller |

## Sending

| AC | Rule |
|---|---|
| AC-38-89 | [BE] JSON `POST /messages` with no `channelId`, when the default is a real guess, answers `422 channel_required` in the gateway's error envelope. No message row, no contact and no queued send result. The message tells the consumer to pass `channelId` |
| AC-38-90 | [BE] Multipart media `POST /messages` behaves the same, and nothing is uploaded. A `channelId` part that is not text answers `422 invalid_channel` |
| AC-38-91 | [BE] The refusal does not use up the Idempotency-Key: a retry with the same key and a `channelId` sends and answers 202. A retry of a send that already completed replays 202 even if the default has since become a guess, on JSON and on multipart |
| AC-38-92 | [BE] The refusal applies whatever the recipient form, including `to:"id:<contactId>"`. With `channelId`, a send with a phone or `id:` recipient goes out on that channel. An unknown, inactive or foreign `channelId` stays `422 invalid_channel` |
| AC-38-93 | [BE] No refusal, same channel as today: one active channel; one active WhatsApp plus web chat or Messenger; two WhatsApp with one paused; two WhatsApp with one disconnected. No active channel stays `409 no_active_channel` |
| AC-38-94 | [BE] `GET /templates` with no `channelId` answers the same `422 channel_required` when the default is a real guess. With `channelId`, and on a workspace where the default is not a guess, it answers as today |
| AC-38-95 | [BE] `GET /channels` shows `isDefault` false on every channel when the default is a real guess, from the same resolver as the send. Amends AC-38-22, whose other clauses stand |
| AC-38-101 | [BE] A `reaction` goes out on the channel of the message it reacts to, and the `message.reaction` event says that channel, from the public gateway and from the inbox. This holds whether the contact has no identity, one, or one on each number. So a `reaction` with no `channelId` is not refused when the default is a real guess. A foreign or unknown `channelId` on a reaction stays `422 invalid_channel`, no active channel stays `409 no_active_channel`, and a valid `channelId` naming another channel does not move it. A reaction to a message on a paused or disconnected channel is refused with a typed error and nothing is sent. A message with no channel keeps today's choice |

## Schema

| AC | Rule |
|---|---|
| AC-38-96 | [BE] A module migration makes `webhook_endpoints.channel_id` nullable. It is idempotent, leaves one head, changes no row, and is applied and checked on a Postgres copy before hand test |

## Dashboard

| AC | Rule |
|---|---|
| AC-38-97 | [BE] `GET /omnichannel/channels/{id}/webhooks` returns that channel's endpoints plus the all-channels endpoints of that channel's tenant and workspace, and never another workspace's |
| AC-38-98 | [FE] Each channel's Webhooks tab shows an all-channels endpoint with an "All channels" label. Edit, rotate, pause, resume, delete and delivery log work as on any other row. The Add endpoint dialog is unchanged and still creates a per-channel endpoint |
| AC-38-99 | [E2E] A recorded real-click run at 1280 and 375 on a real stack: the row and its label show on two channels of one workspace, pausing it from one shows it paused on the other |

## Contract

| AC | Rule |
|---|---|
| AC-38-100 | [T] `documentation/omnichannel/consumer-integration-guide.md`: section 2 and section 4 state the refusal and the rule, section 5a `isDefault`, section 7 registration covers all channels and `channelId` can be null on an endpoint and on `contact.updated`, `channel_required` in the error table, route table, and a changelog row that says breaking. `documentation/engineering/omnichannel-service.md` is updated |
