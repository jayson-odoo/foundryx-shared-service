# Plan 38 gap 7: workflows under the API key

Status: draft, written 2026-11-04, awaiting plan review. Nothing built.

UAC: `38-gap7-key-workflows-acceptance-criteria.md`, AC-38-120 to AC-38-148. Size L: a module migration, a public contract change, two small core engine seams, and a change to the shared outbound guard. No UI change. Build branch `crew/ss-fuji-gap7-workflows` from main.

## Rulings

- Every API key can configure the workflows of its own workspace. There is no per-key scope, no switch on the key form, no Edit action and no UI change. Staff permissions do not change.
- Workflows built through a key are owned by the key's workspace.
- Allow-list default for key callers: no `code.run` and no AI nodes. `http.request` is allowed under the existing outbound guard. The list is one named constant.
- Business hours stay per workspace with a tenant default, with no per-channel hours. A key can read and set its own workspace's hours.
- Run for one contact accepts capped string `inputs`.
- `DELETE` archives and never hard deletes.

## Design

```text
app_omnichannel.workflow_owners    (tenant_id, workflow_id UNIQUE, workspace_id, created_by, created_at)
                                   workflow_id = plain indexed column, soft ref to core public.workflows.id

key request
  get_api_workspace                tenant, workspace, key from the key only; plan 50 limits; read txn released
  owner repo                       workflows JOIN workflow_owners ON tenant_id AND workspace_id = key's, not trashed
                                   miss -> 404 not_found (same body for unowned, other workspace, foreign tenant, archived, unknown)
  key_workflows service            allow-list -> pin literal ids -> stamp trigger workspace -> WorkflowService(actor=None, actor_id="apikey:<id>")

save / validate / publish          node type not in KEY_WORKFLOW_NODE_TYPES -> 422 node_not_allowed
                                   literal id outside the workspace        -> 422 invalid_definition
run start (run, resume, debug)     core run guard -> module guard: owned and a node outside the list -> run failed, no node executed
run, each omnichannel action       owner workspace from db.info["workflow_origin"] -> every resolve filtered by it
event matching                     omnichannel trigger refine honours the stamped workspaceId, message_received included
run for one contact                contact resolved in the key's workspace -> WorkflowService.run_shortcut(inputs) -> trigger.input.<key>
```

Backfill: none. Every workflow that exists today stays unowned and dashboard only. Handing existing staff workflows to a workspace would show them to that workspace's keys, and nothing in a workflow says which workspace it serves without guessing (foolproof rule: never auto-derive an ambiguous action). Staff assigning a workflow to a workspace is deferred.

## Changes

Paths are under `service_backend/modules/omnichannel/` unless they start with `app/`.

| Area | File | Change |
|---|---|---|
| Model | `models.py` | `WorkflowOwner`, table `workflow_owners`: `id`, `tenant_id`, `workflow_id` (unique, indexed, no cross-schema FK), `workspace_id` (FK `workspaces.id`), `created_by`, `created_at` (`UTCDateTime`) |
| Migration | `alembic/versions/0024_omni_workflow_owner.py` | Create the table and its indexes. Revision id `0024_omni_workflow_owner` (24 characters), down_revision `0023_omni_webhook_all_channels`, one head. Idempotent. No data step. Downgrade drops the table: owned workflows become unowned and stay in the dashboard |
| Repository | `repositories/workflow_owner_repository.py` | Owned list (keyset paged), owned get, count of owned and not archived, insert. Every query filters `tenant_id` and `workspace_id` and joins `Workflow` on the same tenant |
| Service | `services/key_workflows.py` | `KEY_WORKFLOW_NODE_TYPES` (AC-38-128), allow-list check, literal id pinning by `NodeField.type`, trigger workspace stamp, catalog build with the workspace's picker options, caps (200 workflows, 200 nodes, inputs). Calls `WorkflowService` create, update, publish, unpublish, set active, archive, versions and runs with `actor=None` and `actor_id="apikey:<keyId>"` |
| Routes | `routers/api_v1.py` | `GET /workflows/catalog`, `POST /workflows/validate` and `GET /workflows/runs/{runId}` before `/workflows/{id}`. Then CRUD, `publish`, `unpublish`, `active`, `versions`, `runs` (GET list, POST run for one contact), and `GET` and `PUT /business-hours`. HTTP and Pydantic only |
| Body read | `routers/api_v1.py` | Definition-bearing routes read the body with `read_capped_json` (`services/webchat_visitor_service.py:374`) at 256 KB, with no transaction open, then do the DB work as the send route does (`routers/api_v1.py:88-160`) |
| Schemas | `schemas.py` | Narrow public shapes: `PublicWorkflowItem`, `PublicWorkflowVersionItem`, `PublicWorkflowRunItem`, `PublicWorkflowRunDetail`, `PublicCatalogResponse`, `PublicBusinessHoursResponse` (dashboard body plus `source`). Core dashboard schemas are not reused, so a dashboard change cannot move the public contract |
| Run pinning | `services/workflow_actions.py` | A helper reads the run's workflow id from `db.info["workflow_origin"]` (`app/workflow_engine/entity_events.py:35`, set at `app/workflow_engine/executor.py:511-513`), looks up the owner once per run, and each omnichannel action adds `workspace_id` to its resolves. The business hours node is one of them (`services/workflow_actions.py:702-723`) |
| Trigger pinning | `workflow_nodes.py:43-48`, the `message_received` refine | Every omnichannel trigger honours a stamped `workspaceId`, including `message_received`, which has only a channel filter today (`workflow_nodes.py:578-583`) |
| Run guard seam | `app/workflow_engine/executor.py` | `register_run_guard(fn)`, the same pattern as `register_wait_cleanup` (`app/workflow_engine/parking.py:46`). Called after each `parse_definition` of a run: `run_workflow` (`:515`), `resume_run` (`:648`), `debug_execute` (`:705`). A guard that raises fails the run with its message before any node executes. No guard registered, no change |
| Module guard | `services/key_workflows.py`, registered at module boot | For an owned workflow, every node type in the executed definition must be in `KEY_WORKFLOW_NODE_TYPES` |
| Shortcut inputs | `app/services/workflow_service.py:525`, `app/workflow_engine/entity_events.py` | `run_shortcut` and `create_run_for_event` take optional `inputs`, written to the trigger payload `input`, which becomes `trigger.input.<key>` (`app/workflow_engine/executor.py:75`, `app/workflow_engine/context.py:28`). The shortcut event itself stays as it is (`entity_events.py:126-156`) |
| Shortcut menu | `services/conversation_service.py` `list_shortcuts` and `run_shortcut` (`:939`) | An owned workflow is listed and runnable only on contacts of its owner workspace (AC-38-142) |
| Business hours | `services/business_hours.py:113,120,136` | The key GET uses `get` plus `resolve` for `source`. The key PUT uses `set`. A parallel first write that hits `uq_omnichannel_settings_ws` (`models.py:887`) rolls back and updates once |
| Outbound guard | `app/services/url_guard.py:40-48` | The blocked set is the AC-38-137 list, IPv4-mapped forms included. One rule for every caller, checked on Python 3.12, the prod image (`service_backend/Dockerfile:16`) |
| Developer Logs | `app/activity_log/redaction.py:35` | Mask `value` in a `{key, value}` row whose `key` matches `_SECRET_KEY_RE` (`:19`) |
| Docs | guide, `engineering/omnichannel-service.md`, `engineering/workflow-engine.md` | AC-38-147 |

Not changed: core `public.workflows`, the dashboard workflow routes, the key form, staff permissions, channel setup (another lane), and the webhook routes.

## Code check 2026-11-04 (overrides the rows above where they differ)

Checked against the code at ebc4aa7f before the first red test. Paths under `service_backend/`.

- **Run pinning reads the run context.** Read the workflow id from `ctx["_workflow.workflowId"]`, which `_prepare_node_context` sets for every node on the run path and the debug path (`app/workflow_engine/executor.py:169-170`, called at `:397` and `:742`). Not from `db.info["workflow_origin"]`: `debug_execute` never sets it, and child runs and `status_machine.py:467` swap it. Today actions resolve records by tenant only: `_load_contact` (`modules/omnichannel/services/workflow_actions.py:72-80`) and `MessageService.send_message` through `repo.get_by_id(contact_id, tenant_id)` (`message_service.py:428`). For an owned run, the contact is checked against the owner workspace before any write. Tags, fields, stages and close reasons already resolve through `contact.workspace_id` (`workflow_actions.py:298,347,408,420`). The business hours node is `:702-735`; it reads `config.workspaceId` (`:714-723`), so it gets pinned.
- **Event isolation goes in `fire_guard`, not only the stamp.** A trigger refine sees only `(config, ev)` (`app/workflow_engine/entity_events.py:326-336`). `message_received` has no `workspaceId` field (`workflow_nodes.py:577-600`, refine `:328-347`), and staff can edit any trigger in the dashboard. So the owner check runs in the omnichannel triggers' `fire_guard`, which gets `(session, wf, config, ev)` (`entity_events.py:386-393`). A module wrapper checks the owner workspace against the event's workspace and then calls the existing once-per-contact guard (`workflow_nodes.py:605-804`). Event workspace: `extra.workspaceId` for `message_received` (`services/inbound_service.py:393`), `record.workspaceId` for contact events (`workflow_nodes.py:424`). The save-time stamp stays on the 8 triggers that have a `workspaceId` field.
- **`broadcast_completed` carries no workspace.** It has no `workspaceId` in its event extra (`broadcast_send_service.py:257-260,463-466`, `broadcast_service.py:732-740`) and its fact attrs leave it out (`workflow_nodes.py:470-486`). Its workspace refine never matches, and it has no `fire_guard` (`:831`). Crew ruling 4 Nov (a): gap 7 fixes the event so it carries `workspaceId` in its extra at all three emit sites, and the trigger gets the owner `fire_guard`. Red-first test: `test_ac_38_134_broadcast_completed_carries_workspace`. A staff broadcast workflow that filters on a workspace and never fired will start firing after deploy. So the PR body carries a read-only prod count query under 'Before deploy': per workspace, the workflows whose trigger is `omnichannel.broadcast_completed` with a workspace filter, and the action types they run. Crew hands it to the owner with the deploy ask. The missing context keys (`broadcastId`, `broadcastName`, `sent`, `failed`) are a separate existing bug and are not in this PR.
- **Run guard sites.** `resume_run` (`executor.py:648`) only requeues, and every pass runs through `run_workflow`. Guard after `parse_definition` at `:515`, and in `debug_execute` after the scratch merge (`:705-730`), before the first node.
- **Shortcut inputs.** The manual run already has `inputs` (`app/services/workflow_service.py:427`, payload `input` at `:464`). Mirror it on `run_shortcut` (`:525`), `build_shortcut_event` (`entity_events.py:126-156`) and `create_run_for_event` (`:467`).
- **WorkflowService signatures.** `create(..., actor_id, actor=None)` `:276`. `update(..., actor=None)` `:293`, with no `actor_id`. `publish(..., actor_id, actor=None)` `:352`. `set_active` `:330`, `archive` `:337`, `restore` `:345` (does not reactivate), `unpublish` `:409`, `list_runs` `:613`, `get_run_detail` `:622`, `list_versions` `:654`. `run()` needs a `User` (`:422`), so the key path never calls it. `created_by` and `published_by` are free strings with no FK (`app/models/workflow.py:73,103,108,150`), so `apikey:<keyId>` fits. With `actor=None`, publish skips the node permission gate and sets `code_authorized_by = actor_id` (`:369`). So the allow-list check runs before every core publish call (K5), and the run guard is the second gate (K4). The dashboard shows `-` for an `apikey:` author (`_user_name` `:136-140`), which AC-38-145 accepts.
- **Edit conflict is module code.** Core has no optimistic concurrency (`update` `:293`, `WorkflowUpdateRequest` `app/schemas/workflow.py:185-188`). The key `PATCH` locks the workflow row (`with_for_update`), compares `updated_at` with `expectedUpdatedAt`, then updates. That is a row lock only; the core table is not altered.
- **Validate** reuses `definition_issues(doc, *, workflow_id)` (`app/workflow_engine/schemas.py:128`). Publish's permission and code-runner checks (`workflow_service.py:362-369`) do not apply on the key path.
- **Catalog.** `NodeField` has `key, label, type, required, mergeable, options, show_when, entity_filter, redacted` (`app/workflow_engine/registry.py:16-37`). The type-level `label`, `description` and `outputs` are on `TriggerDef` (`:105`) and `ActionDef` (`:143`). The registry has no `kind`, so the catalog sets `trigger`, `action` or `if` itself. IF is not registered: it is type `if` (`executor.py:244`, `service_frontend/lib/workflow-catalog.ts:1201`), so its catalog entry is hand-written, and `if` is in `KEY_WORKFLOW_NODE_TYPES`. The shortcut entity key is `entityType` (`registry.py:376-384`). Picker options come from `WorkflowService.metadata` `omnichannelWorkspaces` (`workflow_service.py:865-1032`) for the key's workspace only. Channels (`:825-843`) are tenant-wide and get filtered by workspace.
- **Body read.** `read_capped_json(request, *, cap)` (`services/webchat_visitor_service.py:374`) raises `WebchatInvalidRequest` (`unsupported_content`, `body_too_large`, `malformed_body`), not `ApiError`. Map it to `422 invalid_request`, as `routers/webchat_public.py:188-192` does, with `cap=256 * 1024`.
- **Run for one contact** resolves `contact` with the find-only `PublicGatewayService._resolve_contact` (`services/public_gateway_service.py:338-352`, `404 contact_not_found`). Never use `_resolve_send_target` (`:223-277`): it creates a contact for a bare value or `phone:`.
- **Business hours.** `get` `:113` (own row only), `set` `:120` (commits at `:132`), `resolve` `:136` (returns `(tz, windows)` with no source). Key `GET`: the own row means `source=workspace`; otherwise `resolve` gives `tenant` or `none`. Body and validators: `BusinessHoursUpdate` (`schemas.py:1384-1391`), `validate_timezone` (`business_hours.py:47-57`), `validate_windows` (`:60-96`). The dashboard routes (`routers/workspaces.py:166-197`) answer 422 with `fieldErrors`.
- **200 cap lock** uses the `webhook_service.py:273-276` pattern (`with_for_update(key_share=True)` on the Workspace row).
- **URL guard.** `_is_blocked_ip` uses the `ipaddress` flags (`app/services/url_guard.py:40-48`), not an explicit list, and `ipaddress` treats some forms differently across Python versions. S3 adds `100.64.0.0/10` by name and unwraps IPv4-mapped forms explicitly, so the AC-38-137 set holds whatever the version. CI and prod run 3.12 (`.github/workflows/deploy.yml:180`, `Dockerfile:16`), and the guard tests run there.
- **Developer Logs** already record key calls under `/api/v1/omnichannel` as `inbound_api` with `api_key_id` (`app/activity_log/middleware.py:288-309`). AC-38-145 needs tests, not new logging.
- **Migration.** The single head is `0023_omni_webhook_all_channels`, and all 25 files use `revision = "..."`.

## Wire contract (Phase 1 block for the tester and the coder)

Base path `/api/v1/omnichannel`, Bearer API key, camelCase, timestamps ISO 8601 with `Z`. Errors use the gateway body `{ "error": { "code", "message", "details"? } }` (guide section 10).

- `PublicWorkflowItem`: `id`, `name`, `description` (string or null), `isActive` (bool), `publishedVersionId` (string or null), `triggerType` (string or null), `draftDefinition` (object), `createdBy` (string), `createdAt`, `updatedAt`.
- `GET /workflows?limit=&cursor=` returns `{ "data": [PublicWorkflowItem], "nextCursor": string or null }`, newest `createdAt` first, ties broken by `id`. `limit` is 1 to 100 (default 50). A bad `limit` or `cursor` answers `422 invalid_request`.
- `POST /workflows` takes `{ name, description?, draftDefinition }` and returns 201 with a `PublicWorkflowItem`. Unknown body keys (`tenantId`, `workspaceId`) are ignored.
- `GET /workflows/{id}` returns 200 with a `PublicWorkflowItem`. `PATCH /workflows/{id}` takes `{ name?, description?, draftDefinition?, expectedUpdatedAt? }` and returns 200 with a `PublicWorkflowItem`. `DELETE /workflows/{id}` returns 204 with an empty body.
- Not found, for every reason: `404 { "error": { "code": "not_found", "message": "Workflow not found." } }`. The body is byte-identical across reasons.
- S2 and S3 routes and shapes follow the UAC; their item fields get added to this block when those slices start.

## Security

- **Scoping.** Tenant and workspace come only from the key (`api_auth.py:63-106`). Every key route goes through the owner repository first, because `WorkflowService.get` is tenant-scoped only. A miss is `404 not_found` with one body for every reason. Red tests on every route use a foreign tenant with the same workspace id, and a second workspace in the same tenant.
- **Allow-list fails closed, twice.** It is checked on create, update, validate and publish, and again at run start through the run guard on all three parse sites, so a version staff publish, an event-fired run, a resumed run and a debug execute of an owned workflow are held to it too. A test pins the constant to the exact AC-38-128 set, so a newly registered node type stays off until someone adds it on purpose. The key path has no user, so the per-node permission gate does not apply there (`app/services/workflow_service.py:259-260`, by design for system paths). The allow-list is the gate on this path.
- **Pinning.** Literal ids are checked at save. Resolved ids are checked at run in each omnichannel action. The trigger workspace is stamped by the server. Owned workflows fire only on their workspace's events.
- **Outbound calls.** `http.request` keeps both guard layers: `assert_deliverable` before the call (`app/workflow_engine/actions/http_actions.py:175`) and `GuardedTransport` at connect (`:194`), with no redirects (`:194`), a wall-clock deadline (`:213`) and a 256 KB cap (`:51`). AC-38-137 names the refused ranges and its test proves that nothing is sent. Who-breaks for the guard rule: see the lane's private notes before merge.
- **Caps.** 200 owned workflows per workspace (count and insert under the workspace row lock), 256 KB bodies, 200 nodes, 20 inputs of at most 1000 characters each. Plan 50 per-key limits apply through `get_api_workspace` (`api_auth.py:83`).
- **Secrets in configs.** Run traces mask `redacted` fields as today (`app/workflow_engine/executor.py:263-300`). Developer Logs mask `{key, value}` header rows (AC-38-146).
- security-reviewer is required on S1 to S5.

## Traps

- The module never alters core `public` tables (`CLAUDE.md:53`). The owner link lives in `app_omnichannel`, and `workflow_id` is a plain column.
- Specific routes go before `/workflows/{id}` (`catalog`, `validate`, `runs/{runId}`).
- The stamped trigger `workspaceId` must survive publish, which copies the draft into the version. The refine reads the published version's config.
- A `message_received` event carries `extra.workspaceId` (`services/inbound_service.py:393`), not `record.workspaceId`; see Code check.
- A staff hard delete in the dashboard leaves an owner row with no workflow. Reads join `workflows`, so the row is invisible. No cleanup machinery.
- `BusinessHoursService.set` commits inside (`services/business_hours.py:132`). The key PUT handles the unique-constraint race once and does not wrap it in a second transaction.
- The dashboard editor sends no `expectedUpdatedAt`, so a staff save never conflicts. Only the key's PATCH can get `409 edit_conflict`.
- `ipaddress` results differ across Python versions for IPv4-mapped addresses. Run the guard tests on 3.12. CI and prod use 3.12 (Code check).
- The guide is the contract. A route or field without its guide text is a review finding (AC-38-147).

## Slices

The tester writes the red tests first from this UAC. Then one coder per lane, continued by message. Slices run in this order on one branch.

| Slice | Who | Content | Red tests, written first |
|---|---|---|---|
| S0 | lead | UAC, plan, this commit | - |
| S1 | tester, then coder | Ownership and CRUD: model, migration, repository, service, routes, schemas. AC-38-120 to AC-38-127 | `tests/test_omnichannel_key_workflows.py`: `test_ac_38_120_every_key_reaches_workflow_routes`, `test_ac_38_120_revoked_401_and_limit_429`, `test_ac_38_121_create_owned_body_tenant_ignored`, `test_ac_38_122_list_own_workspace_only_paged`, `test_ac_38_123_not_owned_uniform_404_every_route` (routes x unowned, other workspace, foreign tenant, archived, unknown; bodies equal), `test_ac_38_124_delete_archives_restore_keeps_owner`, `test_ac_38_126_second_key_sees_revoke_keeps_running`, `test_ac_38_127_cap_200` |
| S2 | tester, then coder | Definition: allow-list, run guard seam and module guard, schemaVersion, caps, `expectedUpdatedAt`, validate, save and run pinning, trigger stamp, catalog. AC-38-128 to AC-38-135 | `tests/test_omnichannel_key_workflow_definitions.py`: `test_ac_38_128_allow_list_is_exactly_the_set`, `test_ac_38_129_refused_on_create_update_validate_publish` (`code.run`, `ai_agent.run`, `assign_conversation`, shortcut on another entity, unknown type, a type registered in the test), `test_ac_38_130_owned_run_refused_before_any_node` (staff-published code node, event run, resumed run, debug execute; unowned control runs), `test_ac_38_131_schema_version_caps_edit_conflict`, `test_ac_38_132_validate_saves_nothing_publish_same_issues`, `test_ac_38_133_literal_ids_pinned_trigger_stamped`, `test_ac_38_134_run_pinning_and_event_isolation`, `test_ac_38_135_catalog_allowed_registered_workspace_options`. `tests/test_workflow_run_guard.py`: `test_guard_refusal_fails_run_with_no_node_executed`, `test_no_guard_no_change` |
| S3 | tester, then coder | `http.request` under the guard, the guard's blocked set, publish, versions, runs, run for one contact with inputs, shortcut menu filter. AC-38-136 to AC-38-142 | `tests/test_omnichannel_key_workflow_http_guard.py`: `test_ac_38_136_http_request_runs_under_guard` (public stub reached, redirect not followed, deadline, cap), `test_ac_38_137_key_workflow_http_request_refuses_private_targets` (one parametrized case per AC-38-137 target, URL passed as a run input, resolver patched for the name case; asserts run failed at the node, later nodes skipped, and zero calls on a spy over `socket.create_connection` and `socket.socket.connect` that records and refuses). `tests/test_url_guard.py`: `test_ac_38_137_blocked_set_covers_listed_ranges`. `tests/test_omnichannel_key_workflow_runs.py`: `test_ac_38_138_publish_versions`, `test_ac_38_139_runs_list_detail_redacted`, `test_ac_38_140_run_for_one_contact` (404 other workspace's contact, 409 per not-runnable reason, actor), `test_ac_38_141_inputs_caps`. `tests/test_omnichannel_shortcuts.py`: `test_ac_38_142_owned_shortcut_listed_on_own_workspace_only` |
| S4 | tester, then coder | Business hours GET and PUT. AC-38-143, AC-38-144 | `tests/test_omnichannel_key_business_hours.py`: `test_ac_38_143_get_source_workspace_tenant_none`, `test_ac_38_144_put_own_row_only_and_validation`, `test_ac_38_144_dashboard_and_node_read_new_value` |
| S5 | tester, then coder | Attribution and the Developer Logs mask. AC-38-145, AC-38-146 | `tests/test_omnichannel_key_workflows.py`: `test_ac_38_145_logs_and_actor_attribution`, `test_ac_38_145_dashboard_routes_serve_key_owned_workflow`. `tests/test_activity_redaction.py`: `test_ac_38_146_key_value_row_masked` |
| S6 | lead | Kill steps below, mutation with `-k` per slice, the migration on a Postgres copy, Postgres race probes (AC-38-127 parallel creates, AC-38-144 parallel first write), SQL for crew's copy, the CI Python check | - |
| S7 | reviewer, security-reviewer | One round, in parallel, with the hard-fail list | - |
| S8 | guide-writer | AC-38-147, before merge | - |
| S9 | tester | AC-38-148: recorded key run on a real stack, then real clicks at 1280 and 375 on a fresh build, one browser at a time | - |

### Kill steps (S6)

Each step changes one thing, runs the named test, which must fail, and is then reverted.

| Step | Change | Must fail |
|---|---|---|
| K1 | Remove `assert_deliverable(url)` (`http_actions.py:175`) and replace `GuardedTransport()` with `httpx.HTTPTransport()` (`:194`) | Every case of `test_ac_38_137_key_workflow_http_request_refuses_private_targets` (the spy sees a connect) |
| K2 | Take the shared address space rule out of the blocked set (`url_guard.py:40-48`) | The `100.64.0.1`, `100.127.255.254` and `[::ffff:100.64.0.1]` cases of the same test, and `test_ac_38_137_blocked_set_covers_listed_ranges` |
| K3 | Remove only `GuardedTransport()`, with the resolver answering a public address first and `10.0.0.7` second | The name case of the same test |
| K4 | Do not register the module run guard | `test_ac_38_130_owned_run_refused_before_any_node`, staff-published code node case |
| K5 | Drop the allow-list check from publish only | `test_ac_38_129_refused_on_create_update_validate_publish`, publish cases |
| K6 | Drop the `workspace_id` filter from the owner join | `test_ac_38_122_*` and `test_ac_38_123_*`, second-workspace cases |
| K7 | Drop the run-time owner filter in `omnichannel.send_message` | `test_ac_38_134_run_pinning_and_event_isolation`, merged-id case |
| K8 | Revert the `{key, value}` mask | `test_ac_38_146_key_value_row_masked` |

## Checks

Targeted only, at most `-n 2`. Touched suites: the new files above, `test_url_guard.py`, `test_http_workflow_action.py`, `test_outbound_connect_address.py`, `test_omnichannel_shortcuts.py`, `test_workflow_shortcuts.py`, `test_omnichannel_business_hours.py`, `test_activity_redaction.py`, `test_activity_log.py`, `test_omnichannel_api_gateway.py`, `test_omnichannel_consumer_webhooks.py` (shared guard). CI runs the full suite on the PR.

## No motion

No UI change. Nothing animates.

## Deferred

Filed in `documentation/backlogs/backlog.md` with the build PR, from BL-SS-335, in neutral wording: staff assigning an existing workflow to a workspace; `schedule.cron` and AI nodes on the key path, on request.

## Definition of Done

1. No mock: there is no frontend change, and S9 runs against the live routes.
2. Backfill: none, by rule, with the reason above (AC-38-125).
3. No tenant-editable key is looked up: the allow-list holds node type keys from code, and records are resolved by id.
4. No new permission, so no grant sweep.
5. S9 at 1280 and 375 on a fresh build against correctly owned ports.
