/**
 * Workflow service boundary (plan sprint-2/08). UI → hook → THIS → api-client.
 * Phase A is mock-bound; Phase B swaps `workflowService` to the real
 * api-client implementation in one line (template-service precedent).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  Workflow,
  WorkflowDebugRequest,
  WorkflowDebugResult,
  WorkflowInput,
  WorkflowListItem,
  WorkflowRunDetail,
  WorkflowRunListItem,
  WorkflowRunRequest,
  WorkflowVersionSummary,
} from '@/types/workflows';
import { realWorkflowService } from './workflow-service.real';

export interface WorkflowService {
  list(query: ListQuery): Promise<ListResult<WorkflowListItem>>;
  /** Record-nav: the row at `index` within the full result set of `query`. */
  getAt(query: ListQuery, index: number): Promise<{ workflow: WorkflowListItem | null; total: number }>;
  get(id: string): Promise<Workflow | null>;
  create(input: WorkflowInput): Promise<Workflow>;
  update(id: string, input: WorkflowInput): Promise<Workflow>;
  remove(id: string): Promise<void>;
  duplicate(id: string): Promise<Workflow>;
  setActive(id: string, isActive: boolean): Promise<Workflow>;
  /** Soft-archive → Trashed/Archived view. */
  archive(id: string): Promise<Workflow>;
  /** Restore from the Archived view. */
  restore(id: string): Promise<Workflow>;
  /** Snapshot the draft → new immutable version → set current (arms the trigger, D4). */
  publish(id: string): Promise<Workflow>;
  /** Clear the current version → trigger stops firing (draft + history kept). */
  unpublish(id: string): Promise<Workflow>;

  /** Manual run (D12/D13) — returns the created run. */
  run(id: string, request: WorkflowRunRequest): Promise<WorkflowRunListItem>;
  listRuns(workflowId: string, query: ListQuery): Promise<ListResult<WorkflowRunListItem>>;
  getRun(runId: string): Promise<WorkflowRunDetail | null>;
  /** Paginated version history (never embedded in the workflow GET). */
  listVersions(workflowId: string, query: ListQuery): Promise<ListResult<WorkflowVersionSummary>>;
  cancelRun(runId: string): Promise<WorkflowRunListItem>;
  /** Staleness-aware single-node debug execute (D16). */
  debugExecute(workflowId: string, request: WorkflowDebugRequest): Promise<WorkflowDebugResult>;

  /** Template picker options for the email.send action (Phase B → GET /templates). */
  listTemplateOptions(): Promise<{ value: string; label: string }[]>;

  /** Tenant workflow settings — run retention (plan 10). */
  getSettings(): Promise<WorkflowSettings>;
  updateSettings(runRetentionDays: number): Promise<WorkflowSettings>;

  export(query: ListQuery, columns: string[]): Promise<string>;
}

export interface WorkflowSettings {
  runRetentionDays: number;
  /** True when no per-tenant override is set (using the deployment default). */
  isDefault: boolean;
}

// Phase B: bound to the real api-client implementation (was mockWorkflowService).
export const workflowService: WorkflowService = realWorkflowService;
