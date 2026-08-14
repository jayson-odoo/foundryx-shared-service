# 17 - Omnichannel × AI Agent workflow nodes

Contract: `17-omnichannel-ai-workflow-agent-acceptance-criteria.md`. Makes the
platform work like respond.io + n8n combined: an inbound WhatsApp message can
start a workflow, pass through an AI Agent node for structured classification,
and reply to the contact - entirely inside the existing workflow engine +
omnichannel module. No new engine, no new subsystem: this wires three already-
built platforms together (workflow engine, omnichannel, the Phase B-i AI core).

## Grill summary (autonomous - resolved from the dispatch brief + codebase research)

The brief specified requirements but left implementation-pattern choices open.
Research findings (see "Reuse map") resolved every branch without needing a
live grill:

- **`ai_agents` (Phase B-i) already exists** - persona (connection + model +
  temperature + skill set) + `AiClient.complete(...)` (the ONE traced LLM seam,
  with `output_schema` → structured JSON output) + a deterministic stub
  provider for dev/test. This is the "AI/LLM integration pattern already
  present" the brief asks to prefer. **No new provider client is built.**
- **The AI Agent workflow node references an existing `AiAgent`** (picked via
  the same `GET /ai/agents` the AI Agents admin page already uses) rather than
  embedding its own connection/model picker. "Model selection" is satisfied by
  proxy - the referenced agent owns connection + model + temperature. This is
  the reuse-mandate call: an agent's persona is already exactly
  {connection, model, temperature, skills}; duplicating that on the node would
  be a parallel one-off. The node adds only what's node-specific: extra
  instructions, the input text, and the output-parameter schema.
- **Trigger scope** ("a specific channel or all channels in the workspace",
  brief §1): implemented as an optional `channelId` on the trigger config -
  unset = fires for any channel on the tenant. A tenant's omnichannel module
  seeds one default "General" workspace; a bare channel filter covers the
  respond.io-parity case without inventing a workspace-picker the brief didn't
  ask for.
- **Extensibility for tools (brief §3, "architect so tools can attach later")**:
  the AI Agent action executor calls `AiClient.complete` with `messages=[...]`
  built from one function (`_build_messages`); attaching MCP/function-calling
  later is a matter of adding a `tools=` argument to that one call site and a
  `tool:*` span kind (`app/models/ai.py` already reserves `SPAN_KINDS` for
  `tool:<name>` - Bi-D17). **No MCP/tool code ships in this slice.**

## Reuse map (what already exists - do not reinvent)

| Need | Existing piece | File |
|---|---|---|
| Node-type registry (trigger/action config schema) | `TriggerDef`/`ActionDef`/`register_trigger`/`register_action` | `app/workflow_engine/registry.py` |
| CRUD/custom-trigger event matching + run creation | `emit_entity_event`/`notify_entity_event`/`_trigger_types_for`/`_passes_refine`/`_create_run` | `app/workflow_engine/entity_events.py` |
| Run-context flattening (payload → `trigger.*`) | `_ctx_from_payload` | `app/workflow_engine/executor.py` |
| Trigger denormalization at publish | `WorkflowService.publish` | `app/services/workflow_service.py` |
| Module boot hook to register nodes | `register_engine_entities()` | `modules/omnichannel/bootstrap.py`, called by `app/module_loader.py` |
| Inbound message commit point | `InboundService._handle_message` (post-commit, mirrors its own `enqueue_event` fire-and-forget pattern) | `modules/omnichannel/services/inbound_service.py` |
| Contact load (tenant-scoped) | `ContactRepository.get_by_id` | `modules/omnichannel/repositories/contact_repository.py` |
| Outbound text send (CSW-enforced, realtime, receipts) | `MessageService.send_message` | `modules/omnichannel/services/message_service.py` |
| AI persona entity | `AiAgent` (connection_id, model, temperature, skills) | `app/models/ai.py` |
| Traced LLM completion w/ structured output | `AiClient.complete(tenant_id, agent, system, messages, output_schema, ...)` | `app/ai/client.py` |
| Deterministic stub LLM (dev/test, no key) | `stub_provider`, `stub_fixtures` | `app/ai/stub.py` |
| Agent picker source | `GET /ai/agents` (`ai_agents.read`) | `app/api/v1/ai.py` |
| Frontend node catalog mirror | `TRIGGER_CATALOG`/`ACTION_CATALOG` | `service_frontend/lib/workflow-catalog.ts` |
| Frontend node config field renderer | `renderField` switch | `service_frontend/components/platform/workflow-canvas/node-config-drawer.tsx` |
| Module-active check already gating the pipeline | `ModuleRepository.is_active` | already called in `InboundService.process_payload` |

## Architecture

### 1. Trigger - `omnichannel.message_received` (module `omnichannel`)

Registered in a new `modules/omnichannel/workflow_nodes.py::register_omnichannel_workflow_nodes()`,
called from `bootstrap.py::register_engine_entities()` (the existing, already-
wired boot hook - no core file gains a module import for this).

```python
TriggerDef(
    key="omnichannel.message_received",
    label="Incoming omnichannel message",
    description="Fires when a WhatsApp message arrives on a chosen channel (or any channel).",
    icon="MessageCircle",
    category="Triggers",
    module="omnichannel",
    fields=[NodeField(key="channelId", label="Channel", type="omnichannelChannel")],
    outputs=[... trigger.message.id/.text/.type/.mediaUrl, trigger.contact.id/.name/.phone,
              trigger.channel.id/.name, trigger.conversationId ...],
)
```

**Dispatch.** `entity_type="omnichannel_message"`, `action="received"`. This
reuses the CRUD/custom-trigger matcher in `entity_events.py` - the same file
that already special-cases `form.submitted` for form-engine (also not a literal
CRUD action). Three small, precedented additions (mirroring the `form.submitted`
branches exactly):

- `_trigger_types_for`: `action == "received"` → `["omnichannel.message_received"]`
- `_passes_refine`: `trigger_type == "omnichannel.message_received"` → compare
  `config.get("channelId")` to `ev["extra"]["channelId"]` (unset config = match any)
- `_create_run`: `ev["action"] == "received"` → `payload["omnichannel"] = ev["extra"]`

`WorkflowService.publish()` gains one branch (mirrors `form.submitted`):
`trigger.type == "omnichannel.message_received"` → `wf.trigger_entity_type = "omnichannel_message"`.

`executor.py::_ctx_from_payload` gains a block flattening `payload["omnichannel"]`
into `trigger.message.*` / `trigger.contact.*` / `trigger.channel.*` /
`trigger.conversationId` (same pattern as the existing `trigger.answers.*` loop
for `form.submitted`).

**Emit point.** `InboundService._handle_message`, right after the existing
`realtime.publish(...)` call (message + contact already committed - line ~199-211
in the current file) and before/alongside the existing `enqueue_event(...)`
consumer-webhook fan-out call that already lives at that exact point. Wrapped in
its own `try/except Exception: logger.exception(...)` (AC-OA-05 - this is on top
of `notify_entity_event`'s own internal dispatch-failure isolation, belt & braces
for the one line, `emit_entity_event`, that isn't itself wrapped):

```python
try:
    from app.workflow_engine.entity_events import notify_entity_event
    notify_entity_event(
        self.db, "omnichannel_message", "received", row,
        tenant_id=channel.tenant_id,
        extra={
            "channelId": channel.id, "channelName": channel.name,
            "workspaceId": channel.workspace_id,
            "contactId": contact.id, "contactName": <first+last or phone>,
            "contactPhone": contact.phone, "conversationId": contact.id,
            "messageId": row.id, "messageType": row.message_type,
            "messageText": row.body, "mediaUrl": message_payload.get("mediaUrl"),
            "mediaMime": row.media_mime,
        },
    )
except Exception:
    logger.exception("workflow trigger dispatch failed for inbound message %s", row.id)
```

No entity registration needed in `app/workflow_engine/entities.py` - `record_facts`
returns `{}` for an unregistered `entity_type` (same as `form_submission` today),
and this trigger doesn't need `record.*` facts (everything needed rides `extra`).

### 2. Actions - `omnichannel.get_contact` / `omnichannel.send_message` (module `omnichannel`)

New `modules/omnichannel/services/workflow_actions.py` (module code depending on
its own repos/services - not core depending on a module):

```python
def omnichannel_get_contact(db, tenant_id, config, ctx) -> dict:
    contact_id = render_field(config.get("contactId"), ctx).strip()
    contact = ContactRepository(db).get_by_id(contact_id, tenant_id)
    if contact is None:
        raise ActionError("Contact not found.")
    return {"id": contact.id, "name": ..., "phone": contact.phone,
            "email": contact.email, "workspaceId": contact.workspace_id,
            "status": ...}

def omnichannel_send_message(db, tenant_id, config, ctx) -> dict:
    contact_id = render_field(config.get("contactId"), ctx).strip()
    text = render_field(config.get("message"), ctx)
    try:
        item = MessageService(db).send_message(
            contact_id, tenant_id, actor_user_id=None,
            payload=SendMessageRequest(messageType="TEXT", body=text),
        )
    except (ThreadNotFound, SendRejected) as exc:
        raise ActionError(str(exc)) from exc
    return {"messageId": item.id, "status": item.deliveryStatus or "QUEUED"}
```

`actor_user_id=None` → `_sender_cols` stamps no `sender_id` (a workflow send is
attributed to the automation, not a human agent - `sender_type` stays `"AGENT"`
on the row per the model default, matching how the existing send path already
treats a send with no acting user). Registered with `requires_connection=None`
(the channel resolves implicitly via `_channel_for_contact`, same as every other
omnichannel send path - no connection field on the node).

### 3. AI Agent action - `ai_agent.run` (module `core`)

New `app/workflow_engine/actions/ai_agent_actions.py`, registered in
`registry.py::_register_core()` alongside `email.send`/`entity.update` (core,
since `ai_agents` is core - Bi-D2: "a workflow action" was explicitly one of the
four reasons `ai_agents` was built as core, not a module).

```python
ActionDef(
    key="ai_agent.run",
    label="AI Agent",
    description="Send content to an AI agent and capture structured output.",
    icon="Sparkles",
    category="Actions",
    executor=ai_agent_run,
    fields=[
        NodeField(key="agentId", label="Agent", type="aiAgent", required=True),
        NodeField(key="instructions", label="Instructions", type="textarea", mergeable=True, required=True),
        NodeField(key="inputText", label="Message", type="textarea", mergeable=True, required=True),
        NodeField(key="outputParams", label="Output parameters", type="outputSchema", required=True),
    ],
    outputs=[],  # dynamic - the frontend lists config.outputParams as nodes.<id>.<key>
)
```

Executor:

```python
def ai_agent_run(db, tenant_id, config, ctx) -> dict:
    agent = db.query(AiAgent).filter(AiAgent.id == config.get("agentId"),
                                      AiAgent.tenant_id == tenant_id).first()
    if agent is None:
        raise ActionError("The selected AI agent was not found.")
    if not agent.is_enabled:
        raise ActionError(f'The agent "{agent.name}" is disabled.')
    system = _build_system(agent)  # equipped skills' active bodies, joined
    instructions = render_field(config.get("instructions"), ctx)
    if instructions:
        system = f"{system}\n\n{instructions}" if system else instructions
    user_text = render_field(config.get("inputText"), ctx)
    output_schema = _schema_from_params(config.get("outputParams") or [])
    try:
        result, _trace = AiClient(db).complete(
            tenant_id=tenant_id, agent=agent, system=system,
            messages=[{"role": "user", "content": user_text}],
            output_schema=output_schema,
        )
    except LLMError as exc:
        raise ActionError(str(exc)) from exc
    return result.structured or ({"text": result.text} if result.text else {})
```

`_schema_from_params` turns the friendly row list
(`[{"key": "intent", "type": "string", "description": "...", "required": true}, ...]`)
into a JSON Schema object (`{"type": "object", "properties": {...}, "required": [...]}`)
- the same "friendly config → interpreted at run time" pattern `entity.update`'s
`assignments` field already uses. `AiClient(db).complete(...)` is the exact seam
`app/ai/grill.py` already calls (see `_complete_traced`) - this executor is a
second, independent caller of the same one seam, not a new code path.

**Loop/actor semantics.** No special handling needed - an `ai_agent.run` node
performs no DB write of its own (LLM call + trace only), so it can never emit a
CRUD event and can never participate in the loop-guard chain; it runs under the
run's existing `workflow_origin` tag like every other action.

### 4. Frontend

- `service_frontend/lib/workflow-catalog.ts`: 4 new entries (1 trigger `module:
  'omnichannel'`, 2 actions `module: 'omnichannel'`, 1 action `ai_agent.run`
  `module: 'core'` - mirrors the backend `ActionDef.module`/`TriggerDef.module`
  already-present field, extended onto the TS types in `types/workflows.ts`).
- `service_frontend/components/platform/workflow-canvas/node-palette.tsx`:
  filter `TRIGGER_CATALOG`/`ACTION_CATALOG` entries whose `module !== 'core'`
  through `useInstalledModules()` (already exists, used for menu gating) before
  building `sections` - the minimal, proportionate compliance with the "New
  catalog checklist rule" (CLAUDE.md `active.py`) for these 3 entries. Building
  a fully generic backend-driven node-catalog-with-module-filtering endpoint is
  explicitly out of scope (backlog BL-SS-030 below) - the existing catalog is
  already a hand-maintained frontend mirror for every other node type, and this
  slice keeps that convention rather than replacing it.
- `service_frontend/components/platform/workflow-canvas/node-config-drawer.tsx`:
  four new `field.type` branches in `renderField`:
  - `'omnichannelChannel'` - `SearchSelect` sourced from `metadata.omnichannelChannels`
    (new array on `WorkflowMetadata`, backend `WorkflowService.metadata()`),
    with an explicit "All channels" option (`value: null`) first - same shape
    as the `'form'` field branch.
  - `'aiAgent'` - `SearchSelect` sourced from `metadata.aiAgents` (new array,
    `{id, name, model}` from `AgentService.list`) - same shape as `'form'`.
  - `'outputSchema'` - a new `OutputParamsEditor` component (sibling of the
    existing `AssignmentsEditor` in the same file): add/remove rows of
    `{key, type: 'string'|'number'|'boolean', description, required}`, key
    uniqueness enforced client-side. Emits the plain array into `config.outputParams`.
  - omnichannel's `contactId`/`message` fields need no new branch - they're
    plain mergeable `text`/`textarea`, already handled by the existing fallback
    branch at the bottom of `renderField`.
- Dynamic-content picker (`upstreamGroups` in `node-config-drawer.tsx`): for an
  `ai_agent.run` node, list `config.outputParams` as `nodes.<id>.<key>` outputs
  (mirrors how `entity`/`form` triggers already inject dynamic outputs from
  their own config - see `triggerOutputItems`).
- `WorkflowMetadata` (`types/workflows.ts` + backend `WorkflowService.metadata()`
  in `app/services/workflow_service.py`) gains `omnichannelChannels: {id, name}[]`
  and `aiAgents: {id, name, model}[]` - both tenant-scoped, both cheap reads
  (channels + agents are small per-tenant tables), following the same shape as
  the existing `forms: []` / `connections: {...}` entries already on that payload.

### 5. Demo flow (dev-only, mirrors `seed_demo_conversations` gating)

New `modules/omnichannel/services/seed_demo_workflow.py::seed_demo_ai_workflow(db, tenant_id)`,
called from the same dev-seed call sites as `seed_demo_conversations`
(`scripts/init_db` / `scripts/bootstrap_db`, `ENVIRONMENT=development` only):

1. Idempotent (`if db.query(AiAgent).filter(AiAgent.key == "omnichannel_demo_classifier")...: return`).
2. Insert one `AiAgent` (`key="omnichannel_demo_classifier"`, `name="Message Classifier"`,
   `connection_id=None` - resolves to the stub provider automatically per
   `AiClient.resolve_for_agent`, since no LLM connection exists in a fresh dev
   DB; zero API key needed for the demo to work out of the box).
3. Insert one published `Workflow` (`name="Demo: classify & reply"`) with 3
   nodes: trigger `omnichannel.message_received` (`channelId: "chn-demo"`) →
   `ai_agent.run` (agent = the seeded agent; instructions = "Classify the
   incoming WhatsApp message's intent, domain and urgency."; inputText =
   `{{ trigger.message.text }}`; outputParams = `intent`, `domain`, `urgency`,
   all `string`, all required) → `omnichannel.send_message` (`contactId:
   "{{ trigger.contact.id }}"`, `message: "Thanks - I've logged this as a
   {{ nodes.<aiNodeId>.intent }} request about {{ nodes.<aiNodeId>.domain }}.
   Someone will follow up shortly."`).
4. `WorkflowService(db).publish(...)` so `trigger_entity_type`/`trigger_type`
   denormalize correctly (never hand-construct the `WorkflowVersion` row).

This satisfies brief requirement #4 end to end using entirely the stub LLM
provider - no product/pricing decision about a default LLM vendor is made or
needed (see "Grill summary").

## Data model changes

None. No new tables, no new columns. `omnichannel.message_received`'s trigger
config (`channelId`) and `ai_agent.run`'s config (`agentId`/`instructions`/
`inputText`/`outputParams`) all live in the existing `workflows.draft_definition_json`
/ `workflow_versions.definition_json` JSON columns, like every other node type.

## Permissions

None new. The 3 omnichannel nodes are gated by the existing `workflows.manage`
(builder)/`workflows.run` perms plus the omnichannel-module-active check
(frontend palette filter + `ModuleRepository.is_active` already in the inbound
pipeline). The AI Agent node's agent picker is gated by the existing
`ai_agents.read`. No grant-sweep needed (DoD gate item 4 - nothing new to grant).

## Backlog items filed

- **BL-SS-030** - Generalize the workflow node palette's module-visibility
  filter (currently a one-off `useInstalledModules()` check added for these 3
  entries) into a backend-driven `module` field consumed uniformly by the
  palette for every future module-contributed node, instead of a hand-filtered
  frontend array. Low priority - the existing catalog is already hand-maintained.
- **BL-SS-031** - MCP / function-calling tool attachment on the AI Agent node
  (explicitly out of scope this slice - see brief). The executor's single
  `messages=[...]` build site and the model's reserved `tool:*` span kind are
  the intended seam.

## Test plan

- **Backend (pytest, Postgres)**: `tests/test_omnichannel_workflow_triggers.py`
  (new) covering AC-OA-01–13 per the acceptance-criteria file, using
  `app.ai.stub.stub_fixtures`/the default deterministic stub for every LLM call
  - no live key anywhere, per the brief's explicit instruction. Extend
  `tests/test_workflow_engine.py` only if a core-registry assertion needs it
  (e.g. `ai_agent.run` present in `list_actions()`).
- **Frontend (Vitest)**: `lib/workflow-catalog.test.ts` additions (entries
  present + typed), a `node-config-drawer` render test per new field type,
  an `OutputParamsEditor` unit test (add/remove/dedupe).
- **E2E (Playwright, real clicks)**: `e2e/omnichannel-ai-workflow.spec.ts` -
  AC-OA-22/23. Delivers the inbound demo message via the same dev
  webhook-simulation mechanism the existing omnichannel E2E specs already use
  (never a raw backdoor DB write), then asserts on the Logs tab + the inbox
  thread. Provisions its own dedicated tenant/workflow name-suffix per the
  spec-isolation rule (parallel suite).
