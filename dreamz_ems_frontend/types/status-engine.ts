/**
 * Status & state-machine engine types (sprint-2/01) — mirrors the backend
 * camelCase wire contracts in app/schemas/status_engine.py.
 */
import type { RuleGroup } from './rules';
import type { TemplateDocument } from './templates';

export interface StatusEntity {
  entityType: string;
  label: string;
  module: string;
  platformOwned: boolean;
  requiredFlags: string[];
  /** Caller-tier stats for the entity list surface. */
  statusCount: number;
  transitionCount: number;
  /** True when the caller's tenant forked this entity's set. */
  customized: boolean;
  /** True when the entity has time-based auto edges — gates "Simulate date". */
  hasTimeAutoEdges: boolean;
}

/** One would-advance row from the admin date-simulation (sprint-4/03 Slice 6). */
export interface SimulateRow {
  id: string;
  label: string;
  fromId: string | null;
  toId: string | null;
}

export interface SimulateResult {
  data: SimulateRow[];
  applied: boolean;
}

export interface StatusFlags {
  isInitial?: boolean;
  isTerminal?: boolean;
  isActive?: boolean;
  blocksAccess?: boolean;
  isArchived?: boolean;
  isDefault?: boolean;
}

export interface StatusNodeData {
  id: string;
  entityType: string;
  key: string;
  label: string;
  color: string;
  sortOrder: number;
  isInitial: boolean;
  isTerminal: boolean;
  isActive: boolean;
  blocksAccess: boolean;
  isArchived: boolean;
  isDefault: boolean;
  positionX: number | null;
  positionY: number | null;
  isSystem: boolean;
  recordCount: number;
}

export type RecipientTargetType = 'USER' | 'ROLE' | 'DYNAMIC';
export type DynamicRecipientKey = 'ACTOR' | 'ASSIGNEE' | 'RECORD_OWNER';
export type NotificationChannel = 'EMAIL' | 'IN_APP';

export interface NotificationRecipient {
  targetType: RecipientTargetType;
  targetId?: string | null;
  dynamicKey?: DynamicRecipientKey | null;
}

export interface TransitionNotification {
  channel: NotificationChannel;
  templateSubject: string;
  templateBody: string;
  templateKey?: string | null;
  /** Engine template (BL-081) — set = render through the template engine;
   * inline subject/body stay as the fallback. */
  templateId?: string | null;
  /** Per-use COPY of a template's block doc (edited inline) — set = render this
   * branded doc (subject = templateSubject). */
  doc?: TemplateDocument | null;
  recipients: NotificationRecipient[];
}

export interface TransitionRole {
  id: string;
  name: string;
}

export interface StatusTransition {
  id: string;
  entityType: string;
  fromStatusId: string;
  toStatusId: string;
  label: string;
  sortOrder: number;
  roles: TransitionRole[];
  notifications: TransitionNotification[];
  /** Rule-engine condition tree (sprint-2/02 D1) — null = unconditional. */
  conditionsJson?: RuleGroup | null;
  /**
   * Derived status (sprint-4/03) — 'manual' = a user fires it (action button);
   * 'auto' = the engine fires it when conditionsJson becomes true. Auto edges
   * are never offered as actions and render distinctly on the canvas.
   */
  triggerMode?: TriggerMode;
}

export type TriggerMode = 'manual' | 'auto';

export interface StatusGraph {
  entityType: string;
  /** Which tier the caller sees — their fork or the platform defaults. */
  source: 'tenant' | 'platform';
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

export interface CreateStatusInput {
  entityType: string;
  /** Scoped machines (sprint-3/01 D4) — the owning record (e.g. form id). */
  scopeId?: string;
  label: string;
  color?: string;
  key?: string;
  flags?: StatusFlags;
  positionX?: number;
  positionY?: number;
}

export interface UpdateStatusInput {
  label?: string;
  color?: string;
  flags?: StatusFlags;
  positionX?: number;
  positionY?: number;
}

export interface CreateTransitionInput {
  entityType: string;
  /** Scoped machines (sprint-3/01 D4) — both endpoints must share this scope. */
  scopeId?: string;
  fromStatusId: string;
  toStatusId: string;
  label: string;
  sortOrder?: number;
  roleIds?: string[];
  notifications?: TransitionNotification[];
  conditionsJson?: RuleGroup | null;
  /** Derived status (sprint-4/03) — 'auto' requires conditions + no roles. */
  triggerMode?: TriggerMode;
}

export interface UpdateTransitionInput {
  label?: string;
  sortOrder?: number;
  roleIds?: string[];
  notifications?: TransitionNotification[];
  conditionsJson?: RuleGroup | null;
  /** Derived status (sprint-4/03) — absent = keep. */
  triggerMode?: TriggerMode;
}
