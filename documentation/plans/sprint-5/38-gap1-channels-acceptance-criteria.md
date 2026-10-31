# Plan 38 gap 1 acceptance criteria: `GET /api/v1/omnichannel/channels`

A consumer that never logs in to SS needs to see which numbers its API key can use, so it can map a `channelId` to a number without asking anyone.

| AC | Rule |
|---|---|
| AC-38-20 | `GET /api/v1/omnichannel/channels` under the API key returns the channels of the key's workspace, oldest first. Tenant and workspace come only from the key, as on every other route in `routers/api_v1.py` |
| AC-38-21 | Each item has exactly `id`, `channelType`, `name`, `status`, `isActive`, `isDefault`, `displayPhoneNumber`, `verifiedName`, `createdAt`. It never exposes `tenantId`, `workspaceId`, `wabaId`, `phoneNumberId`, `widgetKey`, credentials or any other internal field |
| AC-38-22 | `isDefault` is true on exactly the channel `POST /messages` uses when `channelId` is omitted, resolved through the same code path, and false on the others. No active channel means none is default |
| AC-38-23 | A disconnected or inactive channel is listed with its real `status` and `isActive: false`, because a consumer must be able to see a number that stopped working. A trashed channel is not listed |
| AC-38-24 | A channel in another workspace or another tenant is never returned. A missing or invalid key gets the same error as the other gateway routes, and so does a workspace whose module is inactive |
| AC-38-25 | The response shape follows the gateway's existing list convention, and the route passes `tests/test_list_pagination_limit.py` and `tests/test_schema_uuid_id_principle.py` |
| AC-38-26 | `documentation/omnichannel/consumer-integration-guide.md` documents the route, the fields and what `isDefault` means, with a changelog entry, and notes that `POST /messages` without `channelId` uses the default channel even if the contact last wrote on another number |

No migration. No new permission: a key can already send on these channels.
