# Plan 38 gap 1 acceptance criteria: `GET /api/v1/omnichannel/channels`

A consumer that never logs in to SS needs to see which numbers its API key can use, so it can map a `channelId` to a number without asking anyone.

| AC | Rule |
|---|---|
| AC-38-20 | `GET /api/v1/omnichannel/channels` under the API key returns the channels of the key's workspace, oldest first. Tenant and workspace come only from the key, as on every other route in `routers/api_v1.py` |
| AC-38-21 | Each item has exactly `id`, `channelType`, `name`, `status`, `isActive`, `isDefault`, `displayPhoneNumber`, `verifiedName`, `createdAt`. It never exposes `tenantId`, `workspaceId`, `wabaId`, `phoneNumberId`, `widgetKey`, credentials or any other internal field. Where a display field holds only the provider's internal number id, because details were not available at connect, `displayPhoneNumber` is null and `name` is `WhatsApp channel` |
| AC-38-22 | `isDefault` is true on exactly the channel `POST /messages` uses when `channelId` is omitted, resolved through the same code path, and false on the others. No active channel means none is default |
| AC-38-23 | A paused channel is listed with its real `status` and `isActive: false`. A disconnected channel is not listed: Disconnect moves it to trash, and a consumer sees it leave the list |
| AC-38-24 | A channel in another workspace or another tenant is never returned. A missing or invalid key gets the same error as the other gateway routes, and so does a workspace whose module is inactive |
| AC-38-25 | The response shape follows the gateway's existing list convention, `{"data": [...]}` as on `GET /templates`, with no pagination: a workspace has only a handful of channels |
| AC-38-26 | `documentation/omnichannel/consumer-integration-guide.md` documents the route, all fields, `status` values and what `isDefault` means, in the section and the appendix index, with a changelog entry. It notes that `POST /messages` without `channelId` uses the default channel even if the contact last wrote on another number, except reactions, which follow the original message's channel. It says `name` is a free-text label set by the workspace, and that `verifiedName` can be null until the channel's details sync |
| AC-38-27 | A gateway API key works only while its tenant may sign in and its workspace is not trashed, the same rule the AutoCount pull gateway follows (`modules/autocount/pull_auth.py`). Otherwise every route using `get_api_workspace` answers the same `403 service_not_enabled` as a disabled service. Restoring the tenant or workspace restores the key |

No migration. No new permission.
