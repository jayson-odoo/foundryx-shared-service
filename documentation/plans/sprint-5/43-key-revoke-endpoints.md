# Plan 43: a key's webhook endpoints when the key is revoked

UAC: `43-key-revoke-endpoints-acceptance-criteria.md`. Size M, no migration: `created_by` already holds `apikey:<id>`. Branch `crew/ss-key-revoke-endpoints`, stacked on plan 38 gap 2. Rebuilt on main once that lands.

## Rulings

- Revoke dialog names the endpoint count, with "Also pause them" on by default. Revoke can be a rotation or a stop, and only staff know which.
- Staff row shows which key made it.
- Same PR: `gateway_key_enabled` applied to delivery.
- Proposed to crew, in this PR unless it objects: a workspace-level staff list, because a channel's tab is not there once every channel is disconnected.

## Design

```text
staff: revoke key K with pauseEndpoints
  ApiKeyService.revoke
    set revoked_at
    WebhookService.pause_for_key(tenant, workspace, K)   ACTIVE rows where created_by = apikey:K
    one commit

fan-out: find endpoints; none -> return
  gateway_key_enabled(tenant, workspace)? else no rows
dispatch: endpoint ACTIVE? gateway_key_enabled? else FAILED, fixed text, counter unchanged
```

## Changes

| Area | File | Change |
|---|---|---|
| Key list | `services/api_key_service.py`, `routers/api_keys.py`, `schemas.py` | `webhookEndpointCount`, one grouped count per list |
| Revoke | `api_key_service.py:66`, `routers/api_keys.py:67` | Optional body `pauseEndpoints`, default true. Commit once: `revoke` must not commit before the pause |
| Deferred | `deferred_actions.py:234` | Read `payload.get("pauseEndpoints")`, anything but `False` means true |
| Webhook service | `services/webhook_service.py` | `pause_for_key` without its own commit, `list_for_workspace` reused by the new staff route, which first checks the workspace is the tenant's |
| Staff items | `routers/webhooks_subs.py` | `registeredByKeyName`, a staff item type so the public `WebhookEndpointItem` stays as it is. One key lookup per list |
| Workspace route | `routers/webhooks_subs.py` | `GET /workspaces/{id}/webhooks`, workspace looked up with tenant |
| Delivery | `services/webhook_delivery.py` | `gateway_key_enabled` in `_fan_out` after endpoints are found, and in `dispatch`. Import it where no cycle forms: `api_auth.py` imports FastAPI, so consider moving the predicate to the service layer with `api_auth` re-exporting it |
| API key screen | `settings/workspaces/components/use-api-key-list.tsx:79` | Count column. A `run` that opens the dialog when the count is above 0, else the deferred action as today. Dialog per `channel-widget-tab.tsx`, no new `confirm:` carve-out |
| Workspace tab | `settings/workspaces/components/use-workspace-form.tsx:264` | Webhooks tab reusing `useWebhookList` with a list source prop and no Add |
| Docs | guide, `engineering/omnichannel-service.md` | AC-43-50 |

No mock: one choice in a dialog on an existing screen, one existing list on one more tab, "simple reuse" rule. No new permission: `api_keys.manage`, `webhooks.read`, `webhooks.manage` cover it. No motion beyond the dialog's existing one.

## Traps

- A key is checked once at the start of a request, so `ApiKeyService.revoke` locks the key row `FOR UPDATE`, and each key write re-reads it with `with_for_update(key_share=True)`, which renders `FOR NO KEY UPDATE`, after its URL check and before its own commit, answering 401 when revoked. No network call under either lock.

- `revoke` is deferred with an undo window and today has no dialog (`use-api-key-list.tsx:87-90`). Check how `ResourceAction.deferred` takes a payload before designing the `run`; extend the shell's type if it cannot, do not hand-roll.
- The tab can show a stale count: after a revoke, reload the list.
- The route and deferred handler both go through `ApiKeyService.revoke`.
- `gateway_key_enabled` reads three rows. It runs only after endpoints are found, and its failure must not stop inbound, so wrap it in the fan-out's existing guard.
- A trashed-workspace delivery must not move `consecutive_failures`, or a restored workspace finds its endpoints auto-disabled.
- Tests through real routes and the real `dispatch`. `test_omnichannel_gateway_key_lifecycle.py` already covers revoke: read it first.
- SQLite cannot show the commit being one: test by forcing the pause to raise and asserting the key is not revoked.
- Public repo: neutral wording in code, tests, commits and PR.

- Rows disabled by a key before this change read "Disabled by user.", the staff reason, so they count as staff pauses until staff resume them. State it on the PR.

## Slices

| Slice | Who | Content |
|---|---|---|
| S1 | tester, then coder | Red then green, backend AC-43-01..32 |
| S2 | tester, then coder | Red then green, frontend AC-43-40, 41 |
| S3 | lead | Targeted mutation |
| S4 | reviewer, security-reviewer | One round, in parallel |
| S5 | guide-writer | AC-43-50, its red first |
| S6 | tester | AC-43-42, one browser at a time, download path set to scratch |

## Definition of Done

Mock swapped: real routes in S6. Backfill: none needed, existing rows already carry `created_by`; rows made by staff read null. No editable key. No new permission. S6 at 1280 and 375 on a fresh build.
