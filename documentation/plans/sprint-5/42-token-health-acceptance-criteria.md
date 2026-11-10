# 42 WhatsApp token health: acceptance criteria

## Journey

1. A number's access token stops working. Within 6 hours the channel shows Error, and the tenant's users with `channels.manage` get one email naming the number.
2. An admin opens Channels, chooses **Replace token** on that row and pastes a new token.
3. The system tries the new token on that same number. If it works, the token is saved in place, the status clears and the webhook subscription is renewed. Conversations, contacts and templates stay.
4. Sends work again. Messages that already failed are not resent.

The admin decides one thing: which token to paste.

## Rulings

Check every 6 hours. One email on the change to Error. The check is the only writer of Error, not a failed send. A token that will expire gets a warning with its date and is still saved. The public API shows the status and does not refuse sends.

## Status rules

- Only Meta error code 190 means a dead token.
- Error is a label. `is_active` is never changed by this feature, so routing, broadcasts and inbound behave as before.
- No schema change. Error has one cause, so its reason is fixed text.

## Backend

- **AC-42-01 [BE]** Given Meta answers a token check with error code 190, the result is dead. Given a 5xx, a transport failure, a rate limit code or a permission code, the result is unknown. Given a success, the result is ok.
- **AC-42-02 [BE]** The periodic scan queues one check per WhatsApp channel that is not trashed, whose tenant has the module active and is not suspended. Paused channels are included. Other channel types and dev credentials are skipped. The scan runs every 6 hours and makes no Meta call itself.
- **AC-42-03 [BE]** Given a dead result, the channel's status becomes ERROR and `is_active` is unchanged. Inbound for that number is still processed, and a send still attempts delivery.
- **AC-42-04 [BE]** Given an ok result on an ERROR channel, the status becomes ACTIVE, or INACTIVE when the channel is paused. On a channel not in ERROR, nothing changes.
- **AC-42-05 [BE]** Given an unknown result, nothing changes and no email goes out.
- **AC-42-06 [BE]** On the change to ERROR, one email goes through `OutboxEmailService.enqueue_raw` to each active user of that tenant holding `channels.manage`, and to no user of another tenant. A second dead check sends none. Recovery then a new death sends one again. The email names the channel and the last digits of its number, carries no token, and does not say Foundryx. An email failure does not stop the status change or fail the check.
- **AC-42-07 [BE]** A check that read a token does not write its result if the channel's stored credentials changed since the read.
- **AC-42-08 [BE]** `POST /omnichannel/channels/{id}/replace-token` with `{accessToken}` needs `channels.manage` (403 without it), answers 404 for another tenant's or a trashed channel, and refuses a non-WhatsApp channel as the sibling routes do.
- **AC-42-09 [BE]** The new token is tried on the channel's `phone_number_id` before anything is saved. If Meta refuses it, or its answer is unknown, the route gives a 422 with a fixed message, and the stored credentials and status are unchanged.
- **AC-42-10 [BE]** On success the credentials are replaced in place: same channel id, same identities, templates and messages. An ERROR status clears per AC-42-04. A paused channel stays paused. Existing credential keys other than the token are kept.
- **AC-42-11 [BE]** The token never appears in a response, a log line, an activity row or an error text.
- **AC-42-12 [BE]** After a successful replace the webhook subscription is renewed and Meta's answer is read. The response carries `subscribed`: true, false, or null when the channel has no WABA id. A failed renewal does not undo the saved token.
- **AC-42-13 [BE]** The replace response carries `tokenExpiresAt` when the token's expiry can be read, else null. The manual connect response carries the same field. An unreadable expiry never blocks a save.
- **AC-42-14 [BE]** A PATCH that does not change `isActive` leaves the status alone, so a rename keeps ERROR. A PATCH that does change `isActive` on an ERROR channel keeps ERROR.
- **AC-42-15 [BE]** The channel list's status filter returns only channels of that status, for each status the screen offers, within the tenant.
- **AC-42-16 [BE]** `GET /api/v1/omnichannel/channels` on an ERROR channel shows `status: ERROR` and `isActive: true`, and a public send on it is not refused by this feature.

## Frontend

- **AC-42-20 [FE]** A WhatsApp channel's action list offers **Replace token** to a user with `channels.manage`, and not on other channel types. It opens a dialog with one password field labelled "Permanent access token (System User)". Save stays disabled while the field is empty. No instructional copy.
- **AC-42-21 [FE]** On success the dialog closes, the list and detail show the new status, and a toast confirms it. When `subscribed` is false or null, or `tokenExpiresAt` is set, the matching warning shows, with the date through `useDatetime`.
- **AC-42-22 [FE]** On a refusal the dialog stays open with the message beside the field and keeps the typed value. A failed request shows the same state.
- **AC-42-23 [FE]** A channel in ERROR shows the existing destructive badge on the list and the detail, and the detail shows the fixed reason "Access token expired or revoked". The list's Error filter shows only those channels.
- **AC-42-24 [FE]** The connect wizard's token field uses the same label and is a password field. When the connect response has `tokenExpiresAt`, the same warning shows.
- **AC-42-25 [FE]** The API contract is documented at the top of the service file. Components call a hook, the hook calls the service.

## End to end

- **AC-42-30 [E2E]** Real clicks at 1280 and 375 on a real stack, with Meta stubbed at the adapter: a channel in ERROR, Replace token refused, then accepted; badge clears, history still there; rename while in ERROR keeps it; filter shows it.

## Docs

- **AC-42-40 [T]** `documentation/omnichannel/consumer-integration-guide.md` says what ERROR means for sends, with a changelog line, and `documentation/engineering/omnichannel-service.md` has the token health rules and the steps for a System User token.

## Not in this plan

Flipping on a failed send. Blocking broadcasts on a dead token. A consumer webhook for channel status. Reminder emails. Warning before a token expires. `sync_config` stamping `last_verified_at` after a failed call. Each goes in `documentation/backlogs/backlog.md`.
