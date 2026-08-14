/**
 * Workflow engine wire contracts (plan sprint-2/08). The block-document
 * analogue: `WorkflowDefinition` is the forever-contract graph — `schemaVersion`
 * at root, `nodes[]` + `edges[]`, editor-agnostic. Mirrors the backend
 * `app/workflow_engine/schemas.py` (Phase B). All datetimes are Z-suffixed UTC
 * strings (ApiModel); render via `useDatetime`.
 */

import type { RuleFactType, RuleGroup } from './rules';
import type { TemplateDocument } from './templates';

/** Node kinds. Slice 08 ships trigger + action; `if` lands in slice 09 (the
 * canvas/executor are built kind-extensible from the start). */
export type WorkflowNodeKind = 'trigger' | 'action' | 'if';

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
  | WorkflowAiOutputParam[]
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

/** One structured-output parameter the AI Agent action asks the model for
 * (plan sprint-4/17) - becomes one JSON-Schema property server-side. */
export interface WorkflowAiOutputParam {
  key: string;
  type: 'string' | 'number' | 'boolean';
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
  /** Output port on the source node — `out` for linear, `true`/`false` for IF. */
  sourcePort?: string;
}

export interface WorkflowDefinition {
  schemaVersion: number;
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
    | 'outputSchema';
  required?: boolean;
  placeholder?: string;
  /** For `select` — static options (dynamic ones resolve in Phase B). */
  options?: { value: string; label: string }[];
  /** Whether the dynamic-content picker attaches to this field. */
  mergeable?: boolean;
  /** Conditional: only shown/required when config[field] === value. */
  showWhen?: { field: string; value: string };
  /** For `entity` — restrict the picker (e.g. only status-engine entities). */
  entityFilter?: 'status';
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
  /** Owning module - see `TriggerCatalogEntry.module`. */
  module?: string;
}

/** The IF node (built-in, not a registered Trigger/Action — D8). Its config is
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

export type NodeCatalogEntry = TriggerCatalogEntry | ActionCatalogEntry | IfCatalogEntry;

// ---- workflow metadata (triggerable entities — D6) ----

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
}

/** A published form selectable by the `form.submitted` trigger (slice 2). Its
 * `fields` are the published version's answer keys — they drive the dynamic
 * `trigger.answers.<key>` outputs in the dynamic-content picker. */
export interface WorkflowFormOption {
  id: string;
  name: string;
  fields: { key: string; label: string }[];
}

/** Tenant-resolved metadata the editor needs to configure slice-09 nodes —
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
  /** Tenant's enabled AI agents - backs the AI Agent action's agent picker
   * (plan sprint-4/17). */
  aiAgents?: { id: string; name: string; model: string }[];
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
}

/** The detail entity. Superset of WorkflowListItem so the ONE action registry
 * (typed for the list item) is reusable on the form surface (shell variance —
 * template-engine precedent). */
export interface Workflow extends WorkflowListItem {
  /** Mutable working copy the editor reads/writes. */
  draftDefinition: WorkflowDefinition;
  /** Id of the published version that fires (null = never published). */
  currentVersionId: string | null;
  /** ONLY the current version (full history is a separate paginated endpoint —
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

export type WorkflowRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';
export type WorkflowNodeRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';
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
  error: string | null;
  createdAt: string;
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

/** Manual-run request: values for the trigger's declared inputs. */
export interface WorkflowRunRequest {
  inputs: Record<string, string | number | boolean>;
  isTest?: boolean;
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
