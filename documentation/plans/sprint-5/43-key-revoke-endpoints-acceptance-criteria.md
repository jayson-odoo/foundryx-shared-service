# Plan 43 acceptance criteria: a key's webhook endpoints when the key is revoked

Plan: `43-key-revoke-endpoints.md`. Builds on plan 38 gap 2.

## Journey

A workspace admin opens the workspace's API Keys tab.

1. Each key shows how many active webhook endpoints it registered.
2. They choose Revoke on a key. With no endpoints, it behaves as today. With some, a dialog names the count and offers "Also pause them", on by default. Revoking during a rotation, they switch it off; revoking a key that should stop, they leave it on.
3. They confirm. The usual undo window runs, and undo cancels both.
4. On the workspace's Webhooks tab they see every all-channels endpoint, whichever channels are live, with the key that registered it, and can pause, edit or delete it there. A channel's Webhooks tab shows the same "registered by".

A consumer rotating its key resumes a paused endpoint with its new key: `POST /webhooks/{id}/enable`.

## Revoke

| AC | Rule |
|---|---|
| AC-43-01 | [BE] Each item of the staff API key list carries `webhookEndpointCount`: ACTIVE endpoints this key registered, in its tenant and workspace, without a query per key |
| AC-43-02 | [BE] Revoking with `pauseEndpoints: true` sets the key revoked and every ACTIVE endpoint it registered to `DISABLED`, in one commit, with `disabled_at` and a `disabled_reason` that says the key was revoked. Endpoints of other keys, staff-created endpoints and endpoints already paused or auto-disabled stay as they are |
| AC-43-03 | [BE] `pauseEndpoints: false` revokes the key and changes no endpoint |
| AC-43-04 | [BE] A revoke with no `pauseEndpoints`, through the route or the deferred action, pauses them. A value that is not a boolean is treated as true |
| AC-43-05 | [BE] The deferred action `api_keys.revoke` carries `pauseEndpoints` in its payload. Cancelling during the undo window changes neither the key nor any endpoint. Repeating a revoke on a revoked key changes nothing, and pauses nothing further |
| AC-43-06 | [BE] Revoke finds endpoints by tenant, workspace and exact `apikey:<id>`. A key of the same name or a foreign tenant's row with the same creator text is untouched |
| AC-43-07 | [BE] A paused endpoint receives no event, and the new key can resume it with `POST /webhooks/{id}/enable`. Resuming clears the reason |

## Who made it

| AC | Rule |
|---|---|
| AC-43-10 | [BE] Staff webhook lists carry `registeredByKeyName`: the key's name when an API key made the row, revoked or not, else null. The public API's endpoint item is unchanged |
| AC-43-11 | [BE] The name is resolved with tenant and workspace, without a query per row. A row whose key no longer exists reads null |

## Workspace list

| AC | Rule |
|---|---|
| AC-43-20 | [BE] `GET /omnichannel/workspaces/{id}/webhooks`, gated by `webhooks.read`, returns the all-channels endpoints of that tenant and workspace, also when every channel is disconnected. Another tenant's workspace id answers 404 |
| AC-43-21 | [BE] Staff edit, rotate, pause, resume, delete and delivery log work on those rows with no live channel |

## When the workspace or tenant is off

| AC | Rule |
|---|---|
| AC-43-30 | [BE] While the key routes would refuse a workspace (`gateway_key_enabled`: tenant may not sign in, module inactive, workspace trashed), no event is queued for any endpoint of that workspace. It is checked only when an endpoint subscribes, so a workspace with none pays nothing |
| AC-43-31 | [BE] A queued delivery reaching its attempt in that state is not sent: the row ends `FAILED` with fixed text, and the endpoint's failure counter does not move |
| AC-43-32 | [BE] A failure in this check never reaches the inbound pipeline or the send path |

## Screens

| AC | Rule |
|---|---|
| AC-43-40 | [FE] API Keys tab: a key with endpoints shows the count. Revoke on it opens the dialog with the count and "Also pause them" on by default. Confirm runs the undo window with the choice. A key with none runs the undo window directly, as today |
| AC-43-41 | [FE] Workspace form has a Webhooks tab, gated by `webhooks.read`, reusing the webhook list with no Add button. Both lists show "Registered by" |
| AC-43-42 | [E2E] Recorded real-click run at 1280 and 375: revoke with the choice on, then off; undo; a row seen on the workspace tab with every channel disconnected, then paused there |

## Contract

| AC | Rule |
|---|---|
| AC-43-50 | [T] Guide section 7: a revoked key's endpoints may be paused by the workspace's staff; `disabledReason` says so; resume with `POST /webhooks/{id}/enable`. Changelog row. `documentation/engineering/omnichannel-service.md` is updated |
