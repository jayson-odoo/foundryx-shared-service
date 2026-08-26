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
  WorkflowTestOptions,
  WorkflowVersionSummary,
} from '@/types/workflows';
import { apiFetch } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import type { WorkflowService, WorkflowSettings } from './workflow-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  if (query.statusView) p.set('status_view', query.statusView);
  return p;
}

export const realWorkflowService: WorkflowService = {
  list(query) {
    return apiFetch<ListResult<WorkflowListItem>>(
      `/workflows?${listParams(query).toString()}`,
    );
  },

  getAt(query, index) {
    const p = listParams(query);
    p.delete('page');
    p.delete('page_size');
    p.set('index', String(index));
    return apiFetch<{ workflow: WorkflowListItem | null; total: number }>(
      `/workflows/at?${p.toString()}`,
    );
  },

  get(id) {
    return apiFetch<Workflow>(`/workflows/${id}`).catch(() => null);
  },

  create(input: WorkflowInput) {
    return apiFetch<Workflow>('/workflows', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  update(id, input: WorkflowInput) {
    return apiFetch<Workflow>(`/workflows/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  remove(id) {
    return apiFetch<void>(`/workflows/${id}`, { method: 'DELETE' });
  },

  duplicate(id) {
    return apiFetch<Workflow>(`/workflows/${id}/duplicate`, { method: 'POST' });
  },

  setActive(id, isActive) {
    return apiFetch<Workflow>(`/workflows/${id}/active`, {
      method: 'POST',
      body: JSON.stringify({ isActive }),
    });
  },

  archive(id) {
    return apiFetch<Workflow>(`/workflows/${id}/archive`, { method: 'POST' });
  },

  restore(id) {
    return apiFetch<Workflow>(`/workflows/${id}/restore`, { method: 'POST' });
  },

  publish(id) {
    return apiFetch<Workflow>(`/workflows/${id}/publish`, { method: 'POST' });
  },

  unpublish(id) {
    return apiFetch<Workflow>(`/workflows/${id}/unpublish`, { method: 'POST' });
  },

  run(id, request: WorkflowRunRequest) {
    return apiFetch<WorkflowRunListItem>(`/workflows/${id}/run`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  getTestOptions(id) {
    return apiFetch<WorkflowTestOptions>(`/workflows/${id}/test-options`);
  },

  listRuns(workflowId, query) {
    const p = new URLSearchParams();
    p.set('page', String(query.page));
    p.set('page_size', String(query.pageSize));
    if (query.segment) p.set('segment', query.segment);
    return apiFetch<ListResult<WorkflowRunListItem>>(
      `/workflows/${workflowId}/runs?${p.toString()}`,
    );
  },

  getRun(runId) {
    return apiFetch<WorkflowRunDetail>(`/workflows/runs/${runId}`).catch(
      () => null,
    );
  },

  cancelRun(runId) {
    return apiFetch<WorkflowRunListItem>(`/workflows/runs/${runId}/cancel`, {
      method: 'POST',
    });
  },

  listVersions(workflowId, query) {
    const p = new URLSearchParams();
    p.set('page', String(query.page));
    p.set('page_size', String(query.pageSize));
    return apiFetch<ListResult<WorkflowVersionSummary>>(
      `/workflows/${workflowId}/versions?${p.toString()}`,
    );
  },

  debugExecute(workflowId, request: WorkflowDebugRequest) {
    return apiFetch<WorkflowDebugResult>(`/workflows/${workflowId}/debug`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  listTemplateOptions() {
    return apiFetch<{ value: string; label: string }[]>(
      '/workflows/template-options',
    );
  },

  getSettings() {
    return apiFetch<WorkflowSettings>('/workflows/settings');
  },

  updateSettings(runRetentionDays: number) {
    return apiFetch<WorkflowSettings>('/workflows/settings', {
      method: 'PUT',
      body: JSON.stringify({ runRetentionDays }),
    });
  },

  async export(query, columns) {
    // No bulk export endpoint - render CSV from a large page client-side.
    const result = await apiFetch<ListResult<WorkflowListItem>>(
      `/workflows?${listParams({ ...query, page: 0, pageSize: 1000 }).toString()}`,
    );
    const body = result.data.map((r) =>
      columns.map((c) =>
        String((r as unknown as Record<string, unknown>)[c] ?? ''),
      ),
    );
    return toCsv(columns, body);
  },
};
