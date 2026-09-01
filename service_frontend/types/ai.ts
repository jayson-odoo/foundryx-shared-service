/**
 * Core AI subsystem wire types (Phase B-i slice 1).
 *
 * Mirror of `app/schemas/ai.py`. Explicit interfaces throughout - no `any`.
 */

/** One skill in an agent's equipped set (AC-BI-06b). */
export interface EquippedSkill {
  id: string;
  name: string;
}

/** A persona: which connection, which model, how hot, which skills it equips. */
export interface AiAgent {
  id: string;
  name: string;
  description: string;
  /** The LLM credential. An agent holds NO API key of its own. */
  connectionId: string | null;
  connectionName: string | null;
  provider: string | null;
  /** A PINNED model id - a retired model fails loudly, never substitutes. */
  model: string;
  temperature: number;
  /** The equipped skill SET (AC-BI-06b) - an agent equips many skills, like a
   *  Claude agent's skill set. Which one runs a grill is slice 3's choice. */
  skills: EquippedSkill[];
  isEnabled: boolean;
  /**
   * Missing-prerequisite warning (AC-BI-06) - the connection is gone, inactive
   * or errored, or no model is pinned. Surfaced BEFORE anything runs.
   */
  warning: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface AiAgentInput {
  name: string;
  description?: string;
  connectionId?: string | null;
  model?: string;
  temperature?: number;
  /** The equipped skill ids (AC-BI-06b). Omit to leave unchanged; [] clears. */
  skillIds?: string[];
  isEnabled?: boolean;
}

/** A versioned prompt artifact - browsable and selectable, never an anonymous
 *  text blob on the agent row. */
export interface AiSkill {
  id: string;
  key: string;
  name: string;
  description: string;
  /** The ACTIVE version's body - what an agent actually runs. */
  body: string;
  activeVersionId: string | null;
  activeVersionNumber: number | null;
  versionCount: number;
  isSystem: boolean;
  /** True = the shared platform-tier default; a tenant edit forks a copy. */
  isPlatform: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface AiSkillInput {
  key: string;
  name: string;
  description?: string;
  body?: string;
}

export interface AiSkillUpdate {
  name?: string;
  description?: string;
  /** A CHANGED body mints a new immutable version + moves the active label. */
  body?: string;
}

/** An immutable prompt version. Never mutated; rollback is a label move. */
export interface AiSkillVersion {
  id: string;
  version: number;
  body: string;
  isActive: boolean;
  createdByName: string | null;
  createdAt: string | null;
}

/** One selectable chat model for the picker. */
export interface AiModelOption {
  id: string;
  label: string;
}

export interface AiModelList {
  data: AiModelOption[];
  /** False = the live catalog call failed and the curated static list is being
   *  served instead. The form still renders either way (AC-BI-05). */
  isLive: boolean;
  message: string | null;
}

/** An LLM connection an agent may point at. */
export interface AiConnectionOption {
  id: string;
  name: string;
  provider: string;
  status: string;
  isPlatform: boolean;
}

/** AC-BI-11 - is any LLM connection configured at all? */
export interface AiPrerequisite {
  hasConnection: boolean;
  connections: AiConnectionOption[];
}

export interface AiSkillOption {
  id: string;
  name: string;
}

/** Span kinds. `tool:<name>` is the open seam for future agent tools. */
export type AiSpanKind = 'llm_call' | 'validate' | 'retry' | (string & {});

export type AiTraceStatus = 'ok' | 'error';

/** One step within a run. Field naming follows OTel GenAI semconv. */
export interface AiSpan {
  id: string;
  parentId: string | null;
  /** Sortable materialised path ("1", "2", "2.1") - the flat list's sort key
   *  today, the tree's tomorrow. */
  dottedOrder: string;
  spanKind: AiSpanKind;
  name: string;
  inputJson: unknown;
  outputJson: unknown;
  tokensIn: number;
  tokensOut: number;
  latencyMs: number;
  status: AiTraceStatus;
  error: string | null;
  startedAt: string | null;
}

/** One run. */
export interface AiTrace {
  id: string;
  conversationId: string | null;
  agentId: string | null;
  agentName: string;
  skillKey: string | null;
  promptVersion: number | null;
  provider: string;
  model: string;
  tokensIn: number;
  tokensOut: number;
  latencyMs: number;
  status: AiTraceStatus;
  error: string | null;
  /** Keeps a trace past the short `ok` retention window. */
  flagged: boolean;
  spanCount: number;
  createdAt: string | null;
}

/** Trace + its ordered FLAT step list (Bi-D17 - no tree renderer in v1). */
export interface AiTraceDetail extends AiTrace {
  spans: AiSpan[];
}
