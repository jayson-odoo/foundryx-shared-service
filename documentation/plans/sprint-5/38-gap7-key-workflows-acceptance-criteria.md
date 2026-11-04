# Plan 38 gap 7 acceptance criteria: workflows under the API key

Status: draft, written 2026-11-04, awaiting plan review. Nothing built.

Plan: `38-gap7-key-workflows.md`.

## Journey

A consumer's system holds one API key for a workspace. Nobody on its side logs in to SS. Its own admins build automation in its own app.

1. It reads `GET /workflows/catalog` and learns which nodes it may use, their fields, the options for its workspace, and what each node outputs.
2. It sends a definition to `POST /workflows/validate` while its admin edits, and shows the issues.
3. It saves with `POST /workflows`, later `PATCH`, then publishes. The workflow now fires on its workspace's events only.
4. It starts the workflow for one contact with `POST /workflows/{id}/runs`, passing a ticket reference in `inputs`. An `http.request` node calls back to its public endpoint with that reference.
5. It reads runs and versions to show its admin what happened.
6. It reads and sets its workspace's business hours.
7. A staff user in SS sees these workflows in the Workflows list, like any other.

Every active key can do this for its own workspace only. There is no scope, no switch and no UI change. Staff permissions do not change.

## Words

- **Owned workflow**: a workflow linked to one workspace by the module's owner table. Only owned workflows are visible to a key.
- **Unowned workflow**: every workflow that exists before this change, and any workflow staff create in the dashboard.
- **Allow-list**: the one named constant `KEY_WORKFLOW_NODE_TYPES` listed in AC-38-128.

## S1 Ownership and CRUD

| AC | Rule |
|---|---|
| AC-38-120 | [BE] Every active key, minted before or after this change, can call every route in this file for its own workspace, and needs no scope, setting or permission. A revoked key gets `401 invalid_api_key` as today. Each call counts toward the key's plan 50 limits and over them answers `429 rate_limited` as today. Staff permissions and screens do not change |
| AC-38-121 | [BE] Given a key of workspace W, when it calls `POST /workflows` with a name, an optional description and a `draftDefinition`, then a workflow is created in the key's tenant, owned by W, with `created_by` = `apikey:<keyId>`, inactive and never published. The response is 201 with the workflow item. Tenant and workspace come only from the key: a `workspaceId` or `tenantId` in the body has no effect |
| AC-38-122 | [BE] `GET /workflows` lists only workflows owned by the key's workspace that are not archived, paged with `limit` (1 to 100, default 50) and `cursor`. It never lists an unowned workflow, one owned by another workspace of the same tenant, or one in a foreign tenant with the same workspace id |
| AC-38-123 | [BE] `GET`, `PATCH`, `DELETE`, `publish`, `unpublish`, `active`, `versions`, `runs` and run-for-one-contact on a workflow that is unowned, owned by another workspace, in a foreign tenant, archived or unknown each answer `404 not_found` with the same body, and change nothing. The same holds for `GET /workflows/runs/{runId}` on a run of such a workflow |
| AC-38-124 | [BE] `DELETE /workflows/{id}` archives the workflow, as the dashboard Archive does, and answers 204. It is never hard deleted. After it, every route answers 404 for it. A staff user can still see it in the dashboard Archived view and restore it. A restored workflow is owned by the same workspace again |
| AC-38-125 | [BE] A module migration adds the owner table. It is idempotent, leaves one head, and is applied and checked on a Postgres copy before hand test. Backfill: none. Every workflow that exists before the migration stays unowned, so no key sees it, and it keeps working in the dashboard as before |
| AC-38-126 | [BE] A second key of the same workspace sees and edits the same owned workflows. Revoking the key that created a workflow does not unpublish, deactivate or archive it |
| AC-38-127 | [BE] A workspace holds at most 200 owned workflows that are not archived. Creating the 201st answers `422 invalid_request`, and nothing is saved. The limit holds under parallel creates: the count and insert run under the workspace row lock |

## S2 Definition, allow-list, pinning, catalog

| AC | Rule |
|---|---|
| AC-38-128 | [BE] The allow-list is one named constant, `KEY_WORKFLOW_NODE_TYPES`. Triggers: `omnichannel.message_received`, `omnichannel.conversation_opened`, `omnichannel.conversation_closed`, `omnichannel.conversation_assigned`, `omnichannel.contact_tag_added`, `omnichannel.contact_tag_removed`, `omnichannel.contact_field_changed`, `omnichannel.lifecycle_changed`, `omnichannel.broadcast_completed`, and `entity.shortcut` with entity `omnichannel_contact` only. Actions: `omnichannel.get_contact`, `omnichannel.send_message`, `omnichannel.add_tag`, `omnichannel.remove_tag`, `omnichannel.update_field`, `omnichannel.update_lifecycle`, `omnichannel.open_conversation`, `omnichannel.close_conversation`, `omnichannel.add_comment`, `omnichannel.ask_question`, `omnichannel.wait`, `omnichannel.business_hours`, `http.request`. The IF node is allowed. Nothing else is |
| AC-38-129 | [BE] `POST /workflows`, `PATCH`, `POST /workflows/validate` and `publish` refuse a definition with any node whose type is not on the allow-list: `422 node_not_allowed`, the message naming the node id and type, nothing saved or published. This covers `code.run`, every `ai_agent.*` node, `omnichannel.assign_conversation`, an `entity.shortcut` on any other entity, an unknown type, and a type registered after this change and not added to the constant |
| AC-38-130 | [BE] At run start, a run of an owned workflow whose executed definition holds a node not on the allow-list fails before any node executes, with error `node_not_allowed` naming the node. Nothing is sent or written by any node. This holds for event-fired runs, run-for-one-contact, a version published by staff in the dashboard, a resumed parked run, and a dashboard debug execute. A run of an unowned workflow is unaffected |
| AC-38-131 | [BE] `draftDefinition` must have `schemaVersion` 1, the same document the dashboard editor writes. Anything else answers `422 invalid_definition`. A body over 256 KB or a definition with more than 200 nodes answers `422 invalid_request`, nothing saved. `PATCH` writes the draft only, and nothing fires until publish. When `PATCH` carries `expectedUpdatedAt` and the workflow changed after it, the answer is `409 edit_conflict` and nothing is saved |
| AC-38-132 | [BE] `POST /workflows/validate` takes a definition and answers 200 with `{ "valid": bool, "issues": [...] }`, and saves nothing. The issues are the publish gate's own messages, plus allow-list and pinning issues. `publish` of a draft with issues answers `422 invalid_definition` with the first issue, and nothing is published |
| AC-38-133 | [BE] On create, update, validate and publish, every literal id in a node config must belong to the key's workspace: workspace, channel, contact, tag, contact field, lifecycle stage, close reason and template. Otherwise the answer is `422 invalid_definition` naming the node and field. A value with a merge token is checked at run instead (AC-38-134). The server sets the trigger's workspace to the key's own on save. A trigger naming another workspace is refused the same way |
| AC-38-134 | [BE] At run, an omnichannel action of an owned workflow resolves every record inside the owner workspace. A merged id that points into another workspace fails that node with a typed error, and nothing is written or sent. An event in workspace W2 never fires a workflow owned by W1, also when the trigger names no channel. Two workspaces of one tenant, one event each: each fires only its own workflow |
| AC-38-135 | [BE] `GET /workflows/catalog` answers with the allow-listed node types that are registered, and only those. Each type comes with `type`, `kind`, `label`, `description`, `fields` (`key`, `label`, `type`, `required`, `options`, `showWhen`, `mergeable`) and `outputs`. Picker options (channels, tags, contact fields, lifecycle stages, close reasons, templates) list the key's workspace only. The IF node is listed with its condition format. Every key of a workspace gets the same answer |

## S3 http.request, publish, versions, runs, run for one contact

| AC | Rule |
|---|---|
| AC-38-136 | [BE] `http.request` is allowed in an owned workflow and runs under the existing outbound guard: https only, address checked before the call and again at connect, no redirect followed, the node's wall-clock deadline, a 256 KB response cap. Header values are masked in the run trace, as today |
| AC-38-137 | [BE] An owned workflow whose `http.request` targets a private or reserved address is refused at run, and nothing is sent: the node fails with the guard's message, later nodes are skipped, and no TCP connect is attempted. Targets: loopback `127.0.0.1` and `[::1]`; RFC 1918 `10.0.0.1`, `172.16.0.1`, `192.168.0.1`; link-local `169.254.169.254` and `[fe80::1]`; shared address space `100.64.0.1` and `100.127.255.254`; IPv6 unique local `[fd00::1]`; the IPv4-mapped forms `[::ffff:10.0.0.1]` and `[::ffff:100.64.0.1]`; and a public-looking name that resolves to `10.0.0.7`. The URL comes in through a run input, so the check is the run-time one. Named test: `test_ac_38_137_key_workflow_http_request_refuses_private_targets`. Killed by removing the guard (plan S6) |
| AC-38-138 | [BE] `publish`, `unpublish` and `active` behave as the dashboard actions do. A publish stores `published_by` = `apikey:<keyId>`. `GET /workflows/{id}/versions` is paged, newest first, and each item has `id`, `versionNumber`, `publishedAt` and `definition` |
| AC-38-139 | [BE] `GET /workflows/{id}/runs` is paged, newest first. `GET /workflows/runs/{runId}` returns the run with its node list (status, input and output, error), with fields the registry marks `redacted` masked |
| AC-38-140 | [BE] `POST /workflows/{id}/runs` with `contact` (the `{identifier}` convention of guide section 6a) starts the published version of an owned, active workflow whose trigger is `entity.shortcut` on contacts, and answers 202 with the run item. A contact not in the key's workspace answers `404 contact_not_found`, no run created. An owned workflow that is unpublished, inactive or has another trigger answers `409 workflow_not_runnable`, and the message names which. The run's `actor_id` is `apikey:<keyId>` |
| AC-38-141 | [BE] `inputs` is optional: an object of at most 20 keys, each key matching `^[A-Za-z][A-Za-z0-9_]{0,39}$`, each value a string of at most 1000 characters. Each becomes `trigger.input.<key>` in the run. Anything else answers `422 invalid_request`, no run created |
| AC-38-142 | [BE] In the inbox Shortcuts menu, an owned shortcut workflow is listed only on contacts of its owner workspace. Running it from the inbox on another workspace's contact answers 404, as any invalid shortcut does today |

## S4 Business hours

| AC | Rule |
|---|---|
| AC-38-143 | [BE] `GET /business-hours` returns the key's workspace hours: `workspaceId`, `timezone`, `windows`, the dashboard body, plus `source`. `source` is `workspace` when the workspace has its own hours, `tenant` when the tenant default applies (then `timezone` and `windows` are the default's), and `none` when neither is set. It never returns another workspace's row |
| AC-38-144 | [BE] `PUT /business-hours` with `timezone` and `windows` writes the key's workspace row only, with the dashboard's validation. A bad body answers `422 invalid_request` with the field errors, nothing written. It never writes the tenant default or another workspace. The dashboard Business hours tab and the business hours node then read the new value. Two parallel first writes both answer 200, and one row remains |

## S5 Audit and Developer Logs

| AC | Rule |
|---|---|
| AC-38-145 | [BE] Every call to these routes appears in Developer Logs, attributed to the key, refusals included. `created_by`, `published_by` and the run actor hold `apikey:<keyId>`. The dashboard Workflows list, detail, Versions and Logs render such a workflow without error |
| AC-38-146 | [BE] In Developer Logs request and response summaries, the `value` of a `{ "key": ..., "value": ... }` row whose `key` matches the secret-key pattern (`authorization`, `token`, `secret` and so on) is masked, as a secret dict key is today. Other rows keep their values |

## Contract and end to end

| AC | Rule |
|---|---|
| AC-38-147 | [T] `documentation/omnichannel/consumer-integration-guide.md`: a new section 6c Workflows (catalog, CRUD, validate, publish, versions, runs, run for one contact with `inputs`, the allow-list, workspace pinning, the outbound URL rule with the refused ranges of AC-38-137, the caps) and a new section 6d Business hours. Rows for `node_not_allowed`, `invalid_definition`, `workflow_not_runnable` and `edit_conflict` in section 10. The quick endpoint index. A changelog row, additive and not breaking. `documentation/engineering/omnichannel-service.md` and `documentation/engineering/workflow-engine.md` (the run-guard seam) are updated |
| AC-38-148 | [E2E] A recorded run on a real stack. A key creates, validates, publishes and runs a workflow for one contact, with an `http.request` to a public test endpoint, and reads the run. Then, with real clicks at 1280 and 375, a staff user finds that workflow in Workflows, opens its Versions and Logs, and sees the run |
