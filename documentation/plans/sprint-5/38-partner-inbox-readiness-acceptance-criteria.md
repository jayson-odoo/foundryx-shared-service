# Plan 38 acceptance criteria: partner inbox readiness

Plan: `38-partner-inbox-readiness.md`. Sections are added per gap as each one is built.

## Gap 3: `message.outbound` webhook event

The consumer keeps its own copy of every conversation. Messages SS sends on its behalf (workflows, broadcasts, inbox agents) must reach that copy.

| AC | Rule |
|---|---|
| AC-38-01 | `message.outbound` is a valid event type for `POST /api/v1/omnichannel/webhooks` and for the session webhook route. It is opt-in: an endpoint not subscribed to it receives nothing new, so existing consumers see no change |
| AC-38-02 | One new outbound message row produces exactly one `message.outbound` delivery per subscribed `ACTIVE` endpoint of that message's channel. This holds for every send path: API `POST /messages` (text, template, media, structured), workflow send nodes, inbox and embed agent sends, broadcast sends |
| AC-38-03 | Envelope `id` is `{messageId}:outbound`, stable across delivery retries. `data` is `{ "message": MessageItem, "contact": ThreadItem, "source": "<api, workflow, inbox or broadcast>" }`, using the same `MessageItem` and `ThreadItem` shapes as `message.inbound` |
| AC-38-04 | A media message carries the same absolute, API-key-authed `mediaUrl` form as `message.inbound` |
| AC-38-05 | No `message.outbound` for: internal notes, reactions (those stay `message.reaction`), inbound messages, migration imports, workflow test sandbox rows. Sandbox rows also emit no `SENT` or `FAILED` `message.status` |
| AC-38-06 | An idempotent API replay (same idempotency key) creates no second row and no second event |
| AC-38-07 | A failure while enqueueing the event never fails or rolls back the send. The caller still gets its normal response and the message is still sent |
| AC-38-08 | An endpoint on another channel, workspace or tenant never receives the event |

## Gap 3 companion: `message.status` matches the guide

The guide promises `SENT` and `FAILED`. Today neither reaches the consumer in the cases below.

| AC | Rule |
|---|---|
| AC-38-09 | When Meta accepts a send, subscribed endpoints receive one `message.status` with `deliveryStatus` `SENT` and id `{messageId}:SENT`. A later Meta `sent` receipt for the same message adds no second event |
| AC-38-10 | When a send fails synchronously (Meta rejection, or a local failure such as a transcode error), subscribed endpoints receive one `message.status` with `deliveryStatus` `FAILED`, id `{messageId}:FAILED`, carrying the error fields the guide documents |
| AC-38-11 | Existing `DELIVERED` and `READ` behaviour is unchanged, and status never moves backward |

## Gap 3 contract

| AC | Rule |
|---|---|
| AC-38-12 | Guide `documentation/omnichannel/consumer-integration-guide.md` documents the event: section 7 table, data shape, index, changelog entry. The frontend event type list includes it |
| AC-38-13 | The Add and Edit endpoint dialog offers "Outbound messages" in its Events picker, so editing an endpoint never hides or silently drops the event. Every labelled event type is offered in the picker. Mock `documentation/mockups/SS-FUJI-READINESS/index.html` approved by crew 2026-11-01 |

## Gap 3 review round

Message status events reach external systems, so what they carry is a contract.

| AC | Rule |
|---|---|
| AC-38-14 | A transient send failure stores generic text on the row, and the real error goes to the log. A later success clears the stored error |
| AC-38-15 | `message.status` carries `errorCode` and `errorMessage` only for `FAILED`, on both the sender path and the receipt path. They are null on `SENT`, `DELIVERED` and `READ` |
| AC-38-16 | On `FAILED`, `errorCode` is the provider's code when there is one, else null, and `errorMessage` is capped at 300 characters. The guide states both |
| AC-38-17 | A reply can only target a customer or agent message. `replyToMessageId` on any other row is rejected with the same error as an unknown message |
| AC-38-18 | Fan-out filters endpoints on tenant, workspace and channel |
| AC-38-19 | The guide states that sender fields on `message.outbound` can be filled, including an `apikey:` sender id for API sends |

## Gap 3 reliability

| AC | Rule |
|---|---|
| AC-38-30 | When retries run out, or an unexpected error stops a send before the provider accepted it, the row becomes `FAILED` and one `message.status` `FAILED` goes out, with generic text for anything unexpected. A worker killed outright is not covered here: see the backlog |
| AC-38-31 | The sender-side event reports the outcome the sender reached, not the row's current status. A receipt arriving right after the commit still gives one `{id}:SENT`, and no duplicate `{id}:DELIVERED` |
| AC-38-32 | `message.outbound` for a voice message reports the type that will be sent, `audio/ogg`, the same as `GET` messages returns afterwards |
| AC-38-33 | A send on a channel with no endpoint subscribed to the event builds no payload, so sends without subscribers do not pay for webhooks |

## Gap 3 error text

| AC | Rule |
|---|---|
| AC-38-34 | Provider error text is normalised where the send error is built: URLs and long opaque strings are removed, then capped. The same text is what the row, the event and the developer logs hold |
| AC-38-35 | A media read failure carries only its status, in the error and in the log |
| AC-38-36 | A broadcast recipient's error text follows the same rule: generic text stored, detail logged |
| AC-38-37 | A database failure while enqueueing a webhook never fails or blocks a send, including a failed insert that leaves the session needing a rollback. The message is still sent and the caller gets its normal response |

## Gap 3 outcome accuracy

| AC | Rule |
|---|---|
| AC-38-38 | A message the provider accepted is never reported `FAILED`. If recording success fails, the row is still moved to `SENT` with its external id, and one `SENT` goes out, so later receipts match |
| AC-38-39 | The provider's error code survives retries: a send that exhausts retries reports the last provider code on `FAILED` |
| AC-38-40 | A failure in the broadcast hook or the realtime publish does not stop the `message.status` event, and leaves the session usable |
| AC-38-41 | The guide describes delivery honestly: normally one `SENT` or `FAILED`, delivery is at-least-once so consumers dedupe on the event id, and `GET` can show generic text on a message still being retried |

## Gap 3 last round

| AC | Rule |
|---|---|
| AC-38-42 | Worker logs do not record the request URLs of media reads |
| AC-38-43 | Receipt error text is normalised the same way as send error text. A failure in the broadcast hook on the receipt path rolls back and does not stop the `message.status` event |
