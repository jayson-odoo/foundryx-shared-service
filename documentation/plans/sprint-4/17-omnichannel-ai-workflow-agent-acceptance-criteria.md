# 17 - Omnichannel × AI Agent workflow nodes - Acceptance Criteria

Contract for `17-omnichannel-ai-workflow-agent.md`. Grill resolved via the dispatch
brief (autonomous crewmate task, no live interactive session) - open branches
resolved by reuse of existing infrastructure (see plan "Decisions"); nothing
pricing-sensitive or product-ambiguous surfaced, so no `needs-decision` was raised.

IDs: `AC-OA-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Slice 1 - Backend: trigger + omnichannel actions + AI Agent action

- **AC-OA-01 [BE]** Given a published workflow whose trigger is "Incoming
  omnichannel message" with no channel filter, when an inbound WhatsApp message
  is processed for any active channel on that tenant, then a `WorkflowRun` is
  created for that workflow (tenant-scoped to the message's tenant).
- **AC-OA-02 [BE]** Given the trigger is configured to a specific `channelId`,
  when an inbound message arrives on a *different* channel, then no run is
  created for that workflow (other tenants'/other channels' workflows unaffected).
- **AC-OA-03 [BE]** Given the trigger fires, the run context exposes
  `trigger.message.id/.text/.type/.mediaUrl`, `trigger.contact.id/.name/.phone`,
  `trigger.channel.id/.name`, `trigger.conversationId`.
- **AC-OA-04 [BE]** Given the omnichannel module is INACTIVE for a tenant, no
  workflow run is created for that tenant's inbound messages (reuses the
  existing `ModuleRepository.is_active` gate already in `InboundService`).
- **AC-OA-05 [BE]** Given workflow dispatch raises for any reason, the inbound
  webhook still returns its normal success payload and the message/contact/
  realtime-publish/consumer-webhook-fanout are unaffected (failure isolation -
  CLAUDE.md "workflow dispatch must never break the triggering request").
- **AC-OA-06 [BE]** "Get Contact" action: given a `contactId` (mergeable,
  defaults to `{{ trigger.contact.id }}`), loads the tenant-scoped Contact and
  outputs `id/name/phone/email/workspaceId/status`.
- **AC-OA-07 [BE]** "Get Contact" given a nonexistent or cross-tenant
  `contactId` → the node fails, the run is marked FAILED, downstream nodes skip.
- **AC-OA-08 [BE]** "Send Message" action: given `contactId` + `message` text,
  sends a TEXT message through the existing `MessageService.send_message` path
  into the triggering conversation (same send/realtime/receipt machinery as a
  human agent's reply).
- **AC-OA-09 [BE]** "Send Message" given the contact's 24h CSW is closed → the
  node fails cleanly (existing `SendRejected` surfaced as an `ActionError`), run
  FAILED, no partial/duplicate send.
- **AC-OA-10 [BE]** AI Agent action: given an existing `AiAgent` + instructions
  + input text + a user-defined output-parameter schema (e.g. intent/domain/
  urgency, each typed string/number/boolean), executing the node calls
  `AiClient.complete` with the merged system/user prompt + a JSON-schema
  `output_schema`, and exposes the returned structured object as
  `nodes.<id>.<param>` in the run context - verified via the repo's existing
  deterministic stub LLM provider (no live API key required).
- **AC-OA-11 [BE]** AI Agent given a missing/disabled/deleted referenced agent
  → the node fails with a clear `ActionError`, run FAILED.
- **AC-OA-12 [BE]** AI Agent node execution writes an `AiTrace`/`AiSpan` row
  (reuses `AiClient`'s existing tracing - visible on the AI Traces surface).
- **AC-OA-13 [BE][T]** pytest (Postgres, per repo convention): trigger
  matching (channel filter + all-channels), context flattening, get_contact
  (found/not-found/cross-tenant), send_message (success/CSW-closed), ai_agent.run
  (structured success via stub, missing agent, `LLMError` propagation),
  `publish()` denormalization of the new trigger type, and one end-to-end test
  (seeded demo workflow fires on a seeded `chn-demo` inbound → AI Agent
  classifies via stub → Send Message lands a reply row in the conversation).
  All LLM calls via the stub provider - zero live key required anywhere.

## Slice 2 - Frontend

- **AC-OA-14 [FE]** The workflow node palette lists "Incoming omnichannel
  message" under Triggers and "Get Contact"/"Send Message" under Actions,
  visible only when the omnichannel module is ACTIVE for the tenant; "AI Agent"
  is listed under Actions, always visible (core, gated only by `workflows.manage`).
- **AC-OA-15 [FE]** The trigger's config drawer offers a searchable channel
  picker (`SearchSelect`) sourced from the tenant's omnichannel channels, with
  an explicit "All channels" default option - no instructional copy on screen.
- **AC-OA-16 [FE]** Get Contact / Send Message config drawers render mergeable
  dynamic-content fields (`contactId`, `message`) whose `{{ }}` picker exposes
  the upstream `trigger.contact.*` / `trigger.message.*` outputs.
- **AC-OA-17 [FE]** AI Agent node config drawer: searchable Agent picker
  (`GET /ai/agents`), mergeable `instructions` + `inputText` fields, and a
  repeatable output-parameter row editor (key / type / description / required).
  Foolproof-UI: only string/number/boolean types are offered - no free-typed
  JSON Schema textbox.
- **AC-OA-18 [FE]** The AI Agent node's structured output parameters appear as
  selectable `{{ }}` tokens for every downstream node once at least one
  parameter is defined (reuses the existing upstream-output picker).
- **AC-OA-19 [FE]** Workflow Logs / run detail shows the AI Agent node's
  output object and the omnichannel trigger/action nodes' input/output like any
  other node - reuses the existing run-node inspector, no new UI surface.
- **AC-OA-20 [FE][T]** Vitest: `workflow-catalog.ts` entries present + typed;
  `node-config-drawer` renders the 4 new field paths (channel picker, agent
  picker, output-parameter editor, omnichannel mergeable fields); output-param
  editor add/remove/dedupe-key validation.

## Slice 3 - Demo flow + E2E

- **AC-OA-21 [BE]** A dev-seeded example workflow exists (mirrors
  `seed_demo_conversations`' `ENVIRONMENT=development`-only gating): trigger
  "Incoming omnichannel message" scoped to `chn-demo` → AI Agent (classifies
  intent/domain/urgency) → Send Message (replies referencing the classified
  intent), published + active, on the tenant `seed_demo_conversations` runs for.
- **AC-OA-22 [E2E]** Real-browser flow: deliver an inbound message on the
  seeded `chn-demo` contact (via the existing dev webhook-simulation path);
  assert a new `WorkflowRun` with SUCCESS status appears in the workflow's Logs
  tab, and an outbound reply bubble appears in the conversation thread in the
  omnichannel inbox.
- **AC-OA-23 [E2E]** Build the workflow from scratch via real clicks: create
  workflow → add the omnichannel trigger → add an AI Agent node (pick an agent,
  write instructions, define output params) → add a Send Message node
  referencing an AI output param via `{{ }}` → publish. No raw URL navigation.

## Out of scope (backlog, do not build here)

- MCP / function-calling tool attachment on the AI Agent node (the node is
  architected so tools can attach later - see plan "Extensibility" - but no
  tool/MCP integration ships in this slice).
- A project-management lookup tool or any other concrete tool.
- Generic module-tagged filtering infrastructure for the workflow node palette
  beyond what's needed to gate the 3 omnichannel entries (see plan "Decisions").
