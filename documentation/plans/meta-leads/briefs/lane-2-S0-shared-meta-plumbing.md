# Lane 2 brief: S0 shared Meta plumbing (release 1 of plan 64)

Branch `sprint-5/lead-capture-s0` (crew may use its own `crew/...` name), base `main`. Size M. Owner approved release 1
on 14/11/2026 ~22:50 and allows autonomous runs; the only owner gate is the Messenger hand test at the end.

Read first:

- **Plan and UAC:** `documentation/plans/sprint-5/64-lead-capture.md` (D3, D5, D15) and
  `64-lead-capture-acceptance-criteria.md` (AC-64-20, 25, 26). These are on PR #236's branch until it merges; copy
  them in if the lane branches from main first.
- **Review:** `documentation/plans/meta-leads/PLAN-meta-lead-ads-14nov.md` sections 4 (R1, R2, R4) and 9.
- **Repo rules:** `PRINCIPLES.md`, `CLAUDE.md`, `service_backend/CLAUDE.md`.

## Goal

Make Meta plumbing shareable so Lead Capture (lane 3+) can use it without importing omnichannel, and fix the two
things that would silently break leads. **Omnichannel behaviour must not change.** No Lead Capture module, table or
UI in this lane.

## Scope

**1. Move to core `service_backend/app/integrations/meta/`** (pure move, re-export shims left in omnichannel so
existing imports keep working):

| What | Current location |
|---|---|
| Graph client helpers | `modules/omnichannel/adapters/meta_graph.py` (`MetaGraphMixin`, `_graph_call`, error helpers, `GraphCall`) |
| Facebook code exchange | `modules/omnichannel/adapters/messenger.py:202` `exchange_code` |
| Long-lived token | `messenger.py:238` `exchange_long_lived_token` |
| Page list | `messenger.py:269` `list_pages` |
| Page subscribe | `messenger.py:297-316` `subscribe_webhook` |
| Webhook signature check | `modules/omnichannel/routers/webhooks.py:37` `_signature_valid` |
| Graph error classification | `meta_graph.py` (invalid token / permission removed / rate limited) |

Dev stub when `META_APP_ID` is unset stays exactly as today.

**2. One Page-subscribe function (D15, R1).** `subscribe_page_fields(page_token, page_id, fields)` in core:

- First `GET /{page_id}/subscribed_apps` and find this app's current `subscribed_fields`.
- Then `POST /{page_id}/subscribed_apps` with the UNION of current and requested fields.
- Never drop a field another feature holds.
- `unsubscribe_page_fields(..., fields)` posts the remainder, or `DELETE` when nothing remains.
- Omnichannel's Messenger connect (`modules/omnichannel/services/meta_connect_service.py:313`) calls it with its
  existing list (`messenger.py:94`).

If the GET fails, fall back to posting requested plus omnichannel's known list. Log it, never block the connect
(today's best-effort rule, AC-CHN-33).

**3. Meta change-handler registry (D5, R2).** `register_meta_change_handler(object, field, provider_module, handler)`
in `app/integrations/meta/webhook_registry.py`:

- One owner per `(object, field)`; a second claimant is a loud boot error. Copy the shape of
  `app/module_platform/public_cors.py:62`.
- `InboundService.process_payload` (`modules/omnichannel/services/inbound_service.py:74`) dispatches every
  `entry[].changes[]` item with a registered owner **first**, before `_resolve_channel` (:81) and the module-active
  check (:89-93).
- The handler gets `(db, object, entry_id, change_value)` and must only enqueue.
- A handler exception is logged and isolated; it never affects omnichannel processing of the same payload.
- With no handler registered, the payload path is byte-for-byte today's.

**4. Graph version (R4).**

- Move the Graph version to one core setting `meta_graph_version` (already `app/config.py:377`, default `v19.0`).
  The frontend default `service_frontend/lib/embedded-signup.ts:21` (`v23.0`) reads the same `NEXT_PUBLIC_` var.
- Do NOT change the default or the deploy var (`.github/workflows/deploy.yml:369`, `docker-compose.yml:58`) in this
  lane. Lane 1 (S-META) picks the version; the bump is a one-line follow-up after an omnichannel smoke on it.

## Tests (tester writes them red first)

- **Unedited suites stay green:** every existing omnichannel suite, with special attention to
  `test_omnichannel_channels_connect.py`, `test_omnichannel_channels_messenger.py`, `test_omnichannel_one_webhook.py`,
  `test_omnichannel_webhooks.py`, `test_omnichannel_meta_*`.
- **Subscribe union:** with httpx MockTransport, the GET returns `messages,leadgen`; a Messenger connect POSTs a set
  containing both. Unsubscribe of `leadgen` keeps the Messenger fields.
- **Registry:**
  - A `page` payload with `changes[{field:"leadgen"}]` reaches the registered handler when the Page has NO Messenger
    channel and when omnichannel is inactive for the tenant.
  - A duplicate registration raises at boot.
  - A handler that raises does not stop a `messaging[]` event in the same payload from being stored.
- **Signature and dev-stub behaviour** are unchanged; the existing tests prove it once they point at the core
  function through the shim.

## Definition of Done (repo gate, `CLAUDE.md` "Definition of Done")

- No frontend change except, at most, reading the version var. No mock.
- No migration (none needed). No new permission.
- The reviewer AND security-reviewer run (webhook ingress and tokens are touched).
- Reuse rule: list in crew-done every moved function, with old -> new `file:line`; no second copy left behind.

## Owner hand test (only gate)

1. On a Page already connected as a Messenger channel, send the Page a message from a personal Facebook account:
   it shows in the inbox as before.
2. Reply from the inbox: it arrives in Messenger.
3. Connect the Page again from the channel wizard: still works, with no change in Meta Business Suite's connected
   apps.
