# Shared Service Platform

Domain language shared by the platform engines and installable Services.

## Language

**Agent conversation**:
A durable conversation that gives one AI Agent node context across multiple workflow runs. It is isolated by tenant, workflow, AI Agent node, and a builder-supplied conversation key. One incoming message starts one workflow run; it does not resume an earlier run. Retained state has no inactivity expiry and remains until a workflow explicitly clears it.
_Avoid_: Paused run, collection session

**Agent state**:
The cumulative typed values retained for an Agent conversation. An AI model proposes an evidence-backed patch from the current message, and deterministic platform logic validates and merges it without replaying the conversation transcript.
_Avoid_: Transcript memory, chat history

**Agent state patch**:
A current-message proposal that updates each stateful output field independently. Every field carries one constrained operation: `set`, `clear`, `no_change`, or `ambiguous`. The deterministic reducer applies `set` and `clear`, preserves `no_change`, and leaves state untouched for `ambiguous` so the workflow can request clarification.
_Avoid_: Whole-state rewrite, global update operation

**Stateful output field**:
An AI Agent output parameter that the workflow builder explicitly chooses to retain across messages in an Agent conversation. Outputs that are not stateful describe only the current workflow run and are never carried into the next run.
_Avoid_: Persist every output, implicit memory

**Agent decision output**:
A normal Boolean or Enum output parameter produced by the AI model from the current message and structured Agent state. Later workflow nodes branch or act on it. The AI Agent does not automatically clear state, send a message, or invoke a downstream system when the decision changes.
_Avoid_: Hidden lifecycle transition, AI Agent side effect

**Agent reply output**:
A transient Text output parameter containing a clarification, confirmation, or other response proposed by the AI model. A later messaging action decides whether and where to send it. The AI Agent never sends the reply itself.
_Avoid_: Implicit send, persisted transcript

**Pending clarification**:
Bounded conversation context containing only the last unresolved question and the stateful output field it targets. It helps the AI model interpret a short next message, then is cleared when that field is resolved. It is not a conversation transcript.
_Avoid_: Chat replay, unbounded message history

**Clear Agent State**:
A generic workflow action that clears the current Agent conversation's retained fields and pending clarification. Collection workflows place it after a successful downstream write, so a failed integration cannot discard an update before it is recorded.
_Avoid_: Manual database cleanup, automatic clear inside the AI Agent

**Serialized workflow execution**:
An opt-in, per-workflow execution policy that prevents runs with the same Correlation key from executing concurrently. Runs for different keys remain parallel. Serialization is a workflow runtime guarantee and is not implicitly enabled merely because a graph contains an AI Agent.
_Avoid_: Global single-file queue, AI-specific concurrency rule

**Correlation key**:
A versioned workflow expression that identifies related runs, such as `{{ trigger.conversationId }}`. Keyed serialization and AI Agent state use the same resolved value. Agent state remains isolated further by tenant, workflow, and AI Agent node ID.
_Avoid_: Separate serialization and memory keys, contact-specific hardcoding

**Agent state record**:
The Postgres source of truth for one Agent conversation and AI Agent node. It stores the accepted typed field values, bounded pending clarification, per-field provenance, and a revision used for concurrency safety. Redis may coordinate queued execution and short-lived locks, but it never owns the only copy of collected state.
_Avoid_: Redis-only memory, process-local memory

**Field provenance**:
Metadata retained with an accepted stateful value: the source workflow run, source message identifier when available, exact supporting text from the current message, and update time. It explains why the field changed without retaining the full conversation transcript.
_Avoid_: Unattributed state, inferred transcript

**Redis action**:
A generic workflow action for explicit Redis operations chosen by the builder. It is separate from the workflow runtime's internal Redis-backed scheduling and serialization responsibilities.
_Avoid_: Requiring builders to assemble runtime safety for Agent state

**Code action**:
A generic workflow action that executes builder-authored Python in a separate restricted task runner and returns a schema-validated JSON object to downstream nodes. The runner receives only explicitly mapped workflow data and has no platform environment, credentials, filesystem, process, or network access. Code can transform accepted Agent outputs, but it cannot replace or bypass the trusted Agent-state reducer.
_Avoid_: In-process `eval`, unrestricted server code, reducer customization

## Example dialogue

**Workflow builder**: The first message did not identify the task. Is the workflow still running?

**Platform engineer**: That run finished after asking a follow-up question. The agent conversation gives the next run the earlier context, so the AI Agent can continue without a paused run.

**Workflow builder**: Does the model rewrite everything it remembers on each message?

**Platform engineer**: No. It proposes changes grounded in the current message, and the platform merges accepted changes into the Agent state.

**Workflow builder**: If a message corrects the status, does it also replace the task or blocker?

**Platform engineer**: No. Each stateful output field has its own operation, so unrelated values remain unchanged.

**Workflow builder**: Does enabling Agent state retain every model output?

**Platform engineer**: No. The builder selects which output fields are stateful. Current-turn outputs such as intent, confidence, or a generated reply remain transient.

**Workflow builder**: How does the workflow know when it has enough information to continue?

**Platform engineer**: The builder defines a Boolean or Enum decision output on the AI Agent, then connects an IF node or another downstream node to that output. State lifecycle remains explicit in the workflow graph.

**Workflow builder**: How does the AI Agent ask for missing information?

**Platform engineer**: The builder defines a transient Text output such as `reply`. A Send Message node can reference that output, so generating a response and delivering it remain separate workflow actions.

**Workflow builder**: Can the next message answer with only "yes" or "tomorrow"?

**Platform engineer**: Yes. The Agent conversation retains the last unresolved question and its targeted field until that field is resolved. Earlier messages are not replayed to the model.

**Workflow builder**: How does the next collection start with empty state?

**Platform engineer**: A Clear Agent State action runs after the PM tool or other downstream write succeeds. The current run keeps its node outputs, while the next incoming message starts with fresh retained state.

**Workflow builder**: Does adding a stateful AI Agent force every run into a queue?

**Platform engineer**: No. Serialized execution is an explicit workflow setting. It orders runs that share the configured key, while unrelated workflows and keys continue in parallel.

**Workflow builder**: Do I configure one key for ordering and another for Agent state?

**Platform engineer**: No. The workflow's Correlation key drives both. Tenant, workflow, and node IDs provide the remaining state isolation automatically.

**Workflow builder**: If Redis restarts, is the collected information lost?

**Platform engineer**: No. Agent state is durable in Postgres. Redis coordinates execution but is not the state store.

**Workflow builder**: Can an operator tell which message changed a retained value?

**Platform engineer**: Yes. Every accepted stateful field carries its own source run, message identifier, supporting text, and update time.
