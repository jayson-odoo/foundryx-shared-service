# Plan 38 gap 2: one webhook for all channels, and naming the channel on send

UAC: `38-gap2-one-webhook-acceptance-criteria.md`. Size L: migration, public contract change, one label on an existing screen. Branch `crew/ss-fuji-gap2`.

## Rulings

- One endpoint per workspace across channels, and a workspace with several channels names the channel on public send.
- Refuse only when the default is a real guess. One WhatsApp plus web chat or Messenger keeps sending on WhatsApp, as guide section 2 promises.
- `to:"id:<contactId>"` is refused the same way. Recipient is contact id or phone; channel is `channelId`.
- `GET /templates` gets the same refusal.
- Public `POST /webhooks` always covers all channels, with no channel field.
- Dashboard shows the row on every channel's Webhooks tab, labelled "All channels". No mock: one label on an existing table.

## Design

```text
webhook_endpoints.channel_id  NULL = all channels of the row's workspace

event on channel C
  enqueue_event(C)            channel_id = C, or NULL, within C's tenant and workspace
    envelope.channelId = C

contact.updated
  latest channel found        enqueue_event(channel)              both kinds, channelId = latest
  no latest channel           enqueue_workspace_event(...)        NULL rows only, channelId = null

_workspace_channel(no id)
  actives oldest first
  pool = active WhatsApp, else all actives
  0 -> 409 no_active_channel
  2+ -> 422 channel_required
  1 -> that one
```

## Changes

| Area | File | Change |
|---|---|---|
| Model | `modules/omnichannel/models.py:792` | `channel_id` nullable, docstring |
| Migration | `modules/omnichannel/alembic/versions/0023_*` | `ALTER COLUMN channel_id DROP NOT NULL`, id at most 32 characters, down_revision `0022_omni_webchat_profile`. Downgrade leaves the column nullable and says why: NULL rows cannot fit the old rule, and deleting them would drop a consumer's registration |
| Resolver | `services/public_gateway_service.py:174` | The pool above. Explicit id branch unchanged |
| `isDefault` | `public_gateway_service.py:1297` | Catch `channel_required` as well as `no_active_channel`. Any other code still raises |
| Filter | `services/webhook_delivery.py:81` | `or_(channel_id == channel.id, channel_id.is_(None))`, keeping the tenant and workspace filters |
| Envelope | `webhook_delivery.py:44` | Allow a null channel. `enqueue_workspace_event` for `contact.updated` with no channel, sharing the row and queue code with `enqueue_event` |
| `contact.updated` | `services/conversation_service.py:494` | Remove the early return for no channel. Go to the workspace path when the channel is missing. One producer only: `conversation_service.py:517` |
| Service | `services/webhook_service.py:155` | `create_for_workspace`, sharing the URL and event checks and the insert with `create`. `MAX_ENDPOINTS_PER_WORKSPACE = 10` counted on NULL rows of the workspace. URL and events checked first, then lock the workspace row (per-channel: the channel row), count, insert |
| Public route | `routers/api_v1.py:463` | Call `create_for_workspace`, and answer `409 no_active_channel` when no channel is active |
| Operator list | `webhook_service.py:229` | `list_for_channel` adds NULL rows of the channel's tenant and workspace |
| Wire | `schemas.py:1723` | `channelId: Optional[str] = None` |
| FE types | `services/whatsapp-webhook-service.ts` and `.mock.ts` | `channelId: string \| null`, one all-channels row in the mock |
| FE row | `settings/channels/components/use-webhook-list.tsx:184` | "All channels" `Badge` beside the name when `channelId` is null |
| Docs | guide and `engineering/omnichannel-service.md` | AC-38-100 |

Not changed: `WebhookEndpointCreateRequest` stays name, url, events, so `channelId` in the body is ignored as any unknown field is today. `message_service.py:231` is the internal fallback for sends that name no channel, and it is not the public default. The gateway passes its resolved channel on every send type except a reaction, which follows its target.

## Traps

- On a NULL row, tenant and workspace are the only boundary. Tests use a foreign tenant with the same workspace id, and a second workspace in the same tenant.
- `WebhookService._get` is tenant-scoped only. Public routes keep using `_own_endpoint` / `get_for_workspace`.
- `_do_send` resolves the channel before it branches on type (`public_gateway_service.py:957`), but `_send_reaction` never uses it (`:1008`). A reaction follows its target, `_channel_for_contact(contact, target.channel_id)` in `message_service.react`, so `channel_required` must not stop it (AC-38-101). The inbox shares `react`. `test_gateway_reaction_cross_workspace_404` (`test_omnichannel_rich_messages.py:1620`) stays as it is and keeps answering 404.
- The resolver runs before the contact is created in `_resolve_send_target`, and must stay first, so a refusal creates nothing.
- `_do_send` runs after the idempotency reservation. A refusal must release the key: pin with a retry test against the real store.
- A guide test takes the first changelog row holding `/channels`. The new row must not contain that text, and PR 156 also adds a row at the top of that table, so expect a small conflict there.
- No backfill: existing per-channel endpoints stay as they are, by ruling.
- Existing tests with two active WhatsApp channels and no `channelId` will go red. Each is reported to the lead with what it asserted before it changes.
- Test real producers and real delivery through the HTTP seam, not a stubbed `enqueue_event`.

- A rollback of the code alone would answer 500 on `GET /webhooks` once NULL rows exist, because the old item type requires a string. The migration downgrade is a no-op. State this on the PR.

## Slices

| Slice | Who | Content |
|---|---|---|
| S0 | lead | UAC, plan |
| S1 | tester | Red, backend: AC-38-80..97 |
| S2 | coder | Migration, model, resolver, delivery, service, route, schema |
| S3 | tester, coder | Red then green, frontend: AC-38-98 vitest, types, mock, label |
| S4 | lead | Mutation with `-k`, migration on a Postgres copy, SQL for crew's copy |
| S5 | reviewer, security-reviewer | One round, in parallel |
| S6 | guide-writer | AC-38-100, before merge |
| S7 | tester | AC-38-99 `agent-browser` run at 1280 and 375, one browser at a time, download path set to scratch |

## Checks

Targeted only, at most `-n 2`. Touched suites: `test_omnichannel_consumer_webhooks.py`, `test_omnichannel_api_gateway.py`, `test_omnichannel_gateway_channels.py`, `test_omnichannel_gateway_channel_selector.py`, `test_omnichannel_outbound_event.py`, `test_omnichannel_rich_messages.py`. CI runs the full suite on the PR.

## No motion

The label is static. Nothing animates.

## Definition of Done

1. No mock left bound: FE reads the real route, checked in S7.
2. Backfill: none, by ruling, stated above.
3. No tenant-editable key is looked up.
4. No new permission: `webhooks.read` and `webhooks.manage` cover the row.
5. S7 at 1280 and 375 on a fresh build.
