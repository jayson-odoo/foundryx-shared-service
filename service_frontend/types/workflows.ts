/**
 * Workflow engine wire contracts (plan sprint-2/08). The block-document
 * analogue: `WorkflowDefinition` is the forever-contract graph - `schemaVersion`
 * at root, `nodes[]` + `edges[]`, editor-agnostic. Mirrors the backend
 * `app/workflow_engine/schemas.py` (Phase B). All datetimes are Z-suffixed UTC
 * strings (ApiModel); render via `useDatetime`.
 */

import type { ContactFieldType } from './omnichannel';
import type { RuleFactType, RuleGroup } from './rules';
import type { TemplateDocument } from './templates';

/** Node kinds. Slice 08 ships trigger + action; `if` lands in slice 09 (the
 * canvas/executor are built kind-extensible from the start). */
export type WorkflowNodeKind = 'trigger' | 'action' | 'if';

export type WorkflowExecutionMode = 'parallel' | 'serialized';

export interface WorkflowExecution {
  mode: WorkflowExecutionMode;
  correlationKey: string;
}

/** A node's config is a free-form bag validated against its catalog entry's
 * field schema. Values are primitives, merge-templated strings, or the
 * structured bags some fields carry (manual inputs, field assignments, the IF
 * node's rule tree). */
export type WorkflowNodeConfig = Record<
  string,
  | string
  | number
  | boolean
  | null
  | string[]
  | WorkflowManualInput[]
  | WorkflowFieldAssignment[]
  | WorkflowKeyValue[]
  | WorkflowAiOutputParam[]
  | WorkflowCodeInput[]
  | WorkflowCodeOutputParam[]
  | RuleGroup
  // A copied template block document (email.send per-use design).
  | TemplateDocument
>;

/** A declared input field on the manual trigger (D12). */
export interface WorkflowManualInput {
  key: string;
  label: string;
  type: 'string' | 'number' | 'boolean';
}

/** One `field ← value` assignment on the `entity.update` action (D8). */
export interface WorkflowFieldAssignment {
  field: string;
  /** Merge-templated literal written to the field. */
  value: string;
}

/** One `key ← value` row shared by the HTTP request node's headers and the
 * Send message / Ask a question template-variable editors (plan 31 §5.3). */
export interface WorkflowKeyValue {
  key: string;
  /** Merge-templated literal. */
  value: string;
}

/** One structured-output parameter the AI Agent action asks the model for
 * (plan sprint-4/17) - becomes one JSON-Schema property server-side. */
export interface WorkflowAiOutputParam {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'enum';
  enumValues?: string[];
  description?: string;
  required?: boolean;
  stateful?: boolean;
}

export interface WorkflowCodeInput {
  key: string;
  value: string;
}

export interface WorkflowCodeOutputParam {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'enum';
  enumValues?: string[];
  description?: string;
  required?: boolean;
}

export interface WorkflowNode {
  id: string;
  kind: WorkflowNodeKind;
  /** Catalog key, e.g. `manual`, `email.send` (`""` only transiently in the UI). */
  type: string;
  config: WorkflowNodeConfig;
  position: { x: number; y: number };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  /** Output port on the source node - `out` for linear, `true`/`false` for IF. */
  sourcePort?: string;
}

export interface WorkflowDefinition {
  schemaVersion: number;
  /** Optional in v1 documents. Omitted means parallel execution. */
  execution?: WorkflowExecution;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

// ---- node catalog (frontend mirror of the backend registry) ----

/** One configurable field rendered in the node drawer. The slice-09 field
 * types (`entity`/`status`/`field`/`cron`/`assignments`) resolve their options
 * from the workflow metadata + the node's own `entityType` config (the
 * entity-scoped pickers read `config.entityType`). */
export interface NodeFieldDef {
  key: string;
  label: string;
  /** `text`/`textarea` accept merge fields (dynamic-content picker). */
  type:
    | 'text'
    | 'textarea'
    | 'select'
    | 'template'
    | 'inputs'
    | 'entity'
    | 'status'
    | 'field'
    | 'cron'
    | 'form'
    | 'assignments'
    | 'omnichannelChannel'
    | 'aiAgent'
    | 'outputSchema'
    | 'clarificationOutput'
    | 'agentNode'
    | 'code'
    | 'codeInputs'
    | 'codeCapabilities'
    // Boolean flags render as a labelled checkbox (no bare `<Select>` for a
    // plain yes/no toggle - matches the existing OutputParamsEditor pattern).
    | 'boolean'
    // Omnichannel-scoped pickers (plan 31 §5.2/§5.3) - each except
    // `omnichannelWorkspace` reads its options from the workspace chosen via
    // this node's `workspaceId` config (AC-WFP-03: disabled + empty until a
    // workspace is chosen).
    | 'omnichannelWorkspace'
    | 'omnichannelTag'
    | 'omnichannelContactField'
    | 'omnichannelLifecycleStage'
    | 'omnichannelCloseReason'
    | 'omnichannelMember'
    /** Approved WhatsApp template picker (send/ask template mode). */
    | 'whatsappTemplate'
    /** Per-placeholder mergeable values for a chosen WhatsApp template. */
    | 'templateParams'
    /** Ask a question's `choice` answer-type option list (capped at 10). */
    | 'choiceList'
    /** `workflow.trigger`'s target-workflow picker. */
    | 'workflowRef'
    /** Generic key/value rows (the HTTP request node's headers). */
    | 'keyValue';
  required?: boolean;
  placeholder?: string;
  /** For `select` - static options (dynamic ones resolve in Phase B). */
  options?: { value: string; label: string }[];
  /** Whether the dynamic-content picker attaches to this field. */
  mergeable?: boolean;
  /** Conditional: only shown/required when config[field] matches `value`
   * (one literal, or one of several - e.g. the HTTP body field shown for
   * BOTH `json` and `text` body modes). */
  showWhen?: { field: string; value: string | string[] };
  /** For `entity` - restrict the picker (e.g. only status-engine entities, or
   * only entities that opt into the `entity.shortcut` trigger). */
  entityFilter?: 'status' | 'shortcut';
  help?: string;
}

/** One output key a node writes to the run context (`trigger.*` / `nodes.<id>.*`). */
export interface NodeOutputDef {
  key: string;
  label: string;
}

export interface TriggerCatalogEntry {
  kind: 'trigger';
  type: string;
  label: string;
  description: string;
  /** lucide icon name resolved by the palette. */
  icon: string;
  category: string;
  fields: NodeFieldDef[];
  /** Output schema seeded into the run context (drives the picker). */
  outputs: NodeOutputDef[];
  /** Owning module - `'core'`/absent = always visible; else gated by the
   * module being ACTIVE for the tenant (plan sprint-4/17, mirrors the backend
   * `TriggerDef.module`). */
  module?: string;
}

export interface ActionCatalogEntry {
  kind: 'action';
  type: string;
  label: string;
  description: string;
  icon: string;
  category: string;
  fields: NodeFieldDef[];
  outputs: NodeOutputDef[];
  /** Action needs a resolvable integration connection (email/storage). */
  requiresConnection?: 'email' | 'storage';
  /** Real side effects that warrant a confirm before a manual/test run (D13). */
  destructive?: boolean;
  /** Dynamic side effects for actions whose operation determines the risk. */
  destructiveWhen?: { field: string; values: string[] };
  /** Optional capability required to add or edit this action. */
  permission?: string;
  /** Owning module - see `TriggerCatalogEntry.module`. */
  module?: string;
  /** Non-empty = a branching action (Ask a question, Business hours) - the
   * executor's `kind === 'if'` port rule generalizes to any action declaring
   * these (plan 31 D-A5-14); the canvas renders one labelled source handle
   * per port instead of the single `out` handle. */
  ports?: string[];
  /** This action PARKS the run keyed by a contact (plan 31 D-A5-7,
   * AC-WFP-51/06) - two runs answering the same contact would race the one
   * wait row. `validateDefinition` (registry-driven, mirrors the backend's
   * `ActionDef.requires_serialized` walk in `definition_issues`) blocks
   * publish for any graph containing one of these unless
   * `execution.mode = "serialized"` with a valid correlation key, using the
   * SAME message the backend produces (`"{label} requires serialized
   * execution and a Correlation key."`). */
  requiresSerialized?: boolean;
}

/** The IF node (built-in, not a registered Trigger/Action - D8). Its config is
 * a rule-engine tree (`conditions`); the drawer renders a `<RuleBuilder>` over
 * the run-context facts and the canvas gives it true/false output ports. */
export interface IfCatalogEntry {
  kind: 'if';
  type: string;
  label: string;
  description: string;
  icon: string;
  category: string;
  fields: NodeFieldDef[];
  outputs: NodeOutputDef[];
}

export type NodeCatalogEntry =
  | TriggerCatalogEntry
  | ActionCatalogEntry
  | IfCatalogEntry;

// ---- workflow metadata (triggerable entities - D6) ----

/** One readable/patchable field on a triggerable entity (the rule-engine fact
 * shape, reused for the field picker + entity.update assignments). */
export interface WorkflowEntityField {
  key: string;
  label: string;
  type: RuleFactType;
}

/** A triggerable entity = a rule-engine fact source + `triggerable` flag (D6).
 * Backs the entity picker, the status pickers (status-engine entities only) and
 * the dynamic `trigger.record.*` outputs. */
export interface WorkflowTriggerableEntity {
  type: string;
  label: string;
  fields: WorkflowEntityField[];
  /** Field keys the `entity.update` action may write (subset of `fields`). */
  writableFields: string[];
  /** Adopts the status engine (status_changed / transition_status apply). */
  hasStatus: boolean;
  statuses: { value: string; label: string }[];
  /** May be the target of the generic `entity.shortcut` trigger (plan
   * sprint-4/27) - backs the entity picker's `entityFilter: "shortcut"`. */
  supportsShortcut: boolean;
}

/** A published form selectable by the `form.submitted` trigger (slice 2). Its
 * `fields` are the published version's answer keys - they drive the dynamic
 * `trigger.answers.<key>` outputs in the dynamic-content picker. */
export interface WorkflowFormOption {
  id: string;
  name: string;
  fields: { key: string; label: string }[];
}

/** One tenant-scoped omnichannel workspace's picker options for the plan-31
 * trigger/step catalog (`GET /workflows/metadata` §5.7) - a workspace-scoped
 * picker (tag/field/stage/reason/member/template) reads ONLY the array under
 * the workspace chosen on that node's `workspaceId` config (AC-WFP-03). */
export interface WorkflowOmnichannelWorkspace {
  id: string;
  name: string;
  contactTags: { id: string; name: string }[];
  // `ContactField.type` (plan 25) - NOT a rule-engine fact type (nothing
  // consumes this today, but the previous `RuleFactType` label was wrong
  // - plan 31 S3 review nit).
  contactFields: { key: string; label: string; type: ContactFieldType }[];
  lifecycleStages: { id: string; name: string }[];
  // The backend already filters to active reasons
  // (`_omnichannel_workspace_options`) - the wire never carries `isActive`
  // (plan 31 S3 review B-1).
  closeReasons: { id: string; name: string }[];
  members: { id: string; name: string }[];
  /** Every template regardless of Meta review status - pickers filter to
   * `status === 'APPROVED'` themselves (foolproof-UI). */
  templates: { id: string; name: string; status: string }[];
}

/** A tenant workflow selectable by `workflow.trigger`'s `workflowId` (plan 31
 * §5.3) - backs the `workflowRef` field type. */
export interface WorkflowRefOption {
  id: string;
  name: string;
}

/** Tenant-resolved metadata the editor needs to configure slice-09 nodes -
 * `GET /workflow-metadata` in Phase B (mock in Phase A). */
export interface WorkflowMetadata {
  entities: WorkflowTriggerableEntity[];
  /** Whether a usable connection exists per type (drives the "no connection"
   * warning on email/storage actions). Absent until metadata loads. */
  connections?: { email: boolean; storage: boolean };
  /** Published forms for the `form.submitted` trigger picker (slice 2). */
  forms?: WorkflowFormOption[];
  /** Tenant's active omnichannel channels - backs the omnichannel trigger's
   * channel picker (plan sprint-4/17). */
  omnichannelChannels?: { id: string; name: string }[];
  /** Tenant's omnichannel workspaces with their tags/fields/stages/reasons/
   * members/templates (plan 31 §5.7). S0: mocked behind the metadata service
   * boundary; S1/S3 wire the real `GET /workflows/metadata` addition. */
  omnichannelWorkspaces?: WorkflowOmnichannelWorkspace[];
  /** Tenant workflows selectable by `workflow.trigger` (plan 31 §5.3). */
  workflows?: WorkflowRefOption[];
  /** Tenant's enabled AI agents - backs the AI Agent action's agent picker
   * (plan sprint-4/17). */
  aiAgents?: { id: string; name: string; model: string }[];
  /** Health of the external Code runner, when the capability is configured. */
  codeRunnerAvailable?: boolean;
  /** The runner's language policy summary, rendered in the Code drawer. */
  codeCapabilities?: string[];
  /** Every trigger/action key the backend registry currently resolves
   * (plan 31 S3 review B-4) - the palette (and every quick-replace/context-
   * menu picker) filters `TRIGGER_CATALOG`/`ACTION_CATALOG` down to this set
   * so a node type with no backend `ActionDef`/`TriggerDef` yet (S4/S5's
   * ask_question/wait/business_hours/http.request) is OMITTED entirely,
   * never offered-then-disabled (foolproof-UI: never a choice guaranteed to
   * 422 at Publish / RuntimeError at Run). Absent (undefined) means the
   * metadata hasn't loaded yet - callers treat that as "show nothing new
   * until we know", never "show everything".
   */
  registeredNodeTypes?: string[];
}

/** One backend-validated sandbox contact/channel pair for test-trigger runs. */
export interface WorkflowOmnichannelTestSource {
  channelId: string;
  channelName: string;
  contactId: string;
  contactName: string;
  contactPhone: string;
}

/** Permission-gated, workflow-specific options for a synthetic trigger run. */
export interface WorkflowTestOptions {
  omnichannelTestSources: WorkflowOmnichannelTestSource[];
}

// ---- entities ----

export interface WorkflowListItem {
  id: string;
  name: string;
  description: string;
  isActive: boolean;
  /** Soft-archived (Trashed/Archived view). */
  isTrashed: boolean;
  triggerType: string;
  triggerLabel: string;
  /** Current published version number (null = never published). */
  currentVersionNumber: number | null;
  /** Draft differs from the published version. */
  hasUnpublishedChanges: boolean;
  lastRunAt: string | null;
  lastRunStatus: WorkflowRunStatus | null;
  updatedAt: string;
}

export interface WorkflowVersionSummary {
  id: string;
  versionNumber: number;
  publishedAt: string;
  publishedByName: string;
  notes: string | null;
  /** Included by the Phase 1 mock for draft-vs-published Code health checks. */
  definition?: WorkflowDefinition;
}

/** The detail entity. Superset of WorkflowListItem so the ONE action registry
 * (typed for the list item) is reusable on the form surface (shell variance -
 * template-engine precedent). */
export interface Workflow extends WorkflowListItem {
  /** Mutable working copy the editor reads/writes. */
  draftDefinition: WorkflowDefinition;
  /** Id of the published version that fires (null = never published). */
  currentVersionId: string | null;
  /** ONLY the current version (full history is a separate paginated endpoint -
   * the version list can grow unbounded, never embed it in the workflow GET). */
  currentVersion: WorkflowVersionSummary | null;
  createdByName: string;
  createdAt: string;
}

export interface WorkflowInput {
  name: string;
  description: string;
  draftDefinition: WorkflowDefinition;
}

// ---- runs ----

/** Load state of `GET /workflows/metadata`, which backs the node palette's
 * registry gate (plan 31 S3 review B-4). The palette renders a skeleton while
 * it loads and an inline error state when it fails, instead of a silently
 * empty catalog (review round 2, R-2). */
export type WorkflowCatalogStatus = 'loading' | 'ready' | 'error';

export type WorkflowRunStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'
  /** Parked at an Ask a question / Wait / Business hours node (plan 31 S6,
   * AC-WFP-65) - the node it is parked at is `pausedNodeId` on the run. */
  | 'waiting';
export type WorkflowNodeRunStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'skipped'
  /** Replay-only override (plan 31 S6, AC-WFP-65): the backend trace row for
   * a parked node is `success` (it did complete its own work before asking
   * the engine to suspend) - `RunReplay` re-labels the ONE node matching
   * `run.pausedNodeId` while `run.status === 'waiting'` so it never reads as
   * a phantom success or failure. */
  | 'waiting';
export type WorkflowRunTrigger = 'manual' | 'schedule' | 'event';

export interface WorkflowRunListItem {
  id: string;
  status: WorkflowRunStatus;
  triggeredBy: WorkflowRunTrigger;
  isTest: boolean;
  actorName: string;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  versionNumber: number;
  correlationKey: string | null;
  error: string | null;
  createdAt: string;
  /** The node id this run is parked at while `status === 'waiting'`, else
   * null (plan 31 S6, AC-WFP-65). */
  pausedNodeId: string | null;
}

export interface WorkflowRunNode {
  nodeId: string;
  nodeType: string;
  status: WorkflowNodeRunStatus;
  inputJson: Record<string, unknown> | null;
  outputJson: Record<string, unknown> | null;
  error: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface WorkflowRunDetail extends WorkflowRunListItem {
  /** The immutable version graph this run executed on (D6 replay). */
  definition: WorkflowDefinition;
  triggerPayload: Record<string, unknown>;
  nodes: WorkflowRunNode[];
}

/** Synthetic event data accepted by the omnichannel trigger test path. */
export interface WorkflowOmnichannelTestTrigger {
  type: 'omnichannel.message_received';
  channelId: string;
  contactId: string;
  messageText: string;
}

export type WorkflowTestTrigger = WorkflowOmnichannelTestTrigger;

/** Draft-run request: manual inputs and, for event triggers, typed test data. */
export interface WorkflowRunRequest {
  inputs: Record<string, string | number | boolean>;
  isTest?: boolean;
  testTrigger?: WorkflowTestTrigger;
}

/** Debug single-node (staleness-aware) execute request (D16). */
export interface WorkflowDebugRequest {
  runId: string;
  targetNodeId: string;
  /** Scratch config edits keyed by node id (not persisted to the draft). */
  scratch: Record<string, WorkflowNodeConfig>;
  /** Node ids the user marked stale by editing (client-tracked). */
  staleNodeIds: string[];
}

export interface WorkflowDebugResult {
  /** Per-node outcomes for the nodes that (re-)executed this pass. */
  nodes: WorkflowRunNode[];
}
