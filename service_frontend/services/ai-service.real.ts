import { apiFetch, apiFetchText } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  AiAgent,
  AiAgentInput,
  AiModelList,
  AiPrerequisite,
  AiSkill,
  AiSkillInput,
  AiSkillOption,
  AiSkillUpdate,
  AiSkillVersion,
  AiTrace,
  AiTraceDetail,
} from '@/types/ai';
import type { AiService } from './ai-service';

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
  return p;
}

function atParams(query: ListQuery, index: number): URLSearchParams {
  const p = listParams(query);
  p.delete('page');
  p.delete('page_size');
  p.set('index', String(index));
  return p;
}

function exportParams(query: ListQuery, columns: string[]): URLSearchParams {
  const p = listParams(query);
  p.delete('page');
  p.delete('page_size');
  p.set('columns', columns.join(','));
  return p;
}

export const realAiService: AiService = {
  // ── agents ────────────────────────────────────────────────────────────
  listAgents(query) {
    return apiFetch<ListResult<AiAgent>>(`/ai/agents?${listParams(query).toString()}`);
  },

  getAgentAt(query, index) {
    return apiFetch<{ agent: AiAgent | null; total: number }>(
      `/ai/agents/at?${atParams(query, index).toString()}`,
    );
  },

  getAgent(id) {
    return apiFetch<AiAgent>(`/ai/agents/${id}`).catch(() => null);
  },

  createAgent(input: AiAgentInput) {
    return apiFetch<AiAgent>('/ai/agents', { method: 'POST', body: JSON.stringify(input) });
  },

  updateAgent(id, input: AiAgentInput) {
    return apiFetch<AiAgent>(`/ai/agents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  removeAgent(id) {
    return apiFetch<void>(`/ai/agents/${id}`, { method: 'DELETE' });
  },

  exportAgents(query, columns) {
    return apiFetchText(`/ai/agents/export?${exportParams(query, columns).toString()}`);
  },

  getPrerequisite() {
    return apiFetch<AiPrerequisite>('/ai/agents/prerequisite');
  },

  listModels(connectionId) {
    return apiFetch<AiModelList>(
      `/ai/agents/models?connection_id=${encodeURIComponent(connectionId)}`,
    );
  },

  listSkillOptions() {
    return apiFetch<AiSkillOption[]>('/ai/agents/skill-options');
  },

  // ── skills ────────────────────────────────────────────────────────────
  listSkills(query) {
    return apiFetch<ListResult<AiSkill>>(`/ai/skills?${listParams(query).toString()}`);
  },

  getSkillAt(query, index) {
    return apiFetch<{ skill: AiSkill | null; total: number }>(
      `/ai/skills/at?${atParams(query, index).toString()}`,
    );
  },

  getSkill(id) {
    return apiFetch<AiSkill>(`/ai/skills/${id}`).catch(() => null);
  },

  createSkill(input: AiSkillInput) {
    return apiFetch<AiSkill>('/ai/skills', { method: 'POST', body: JSON.stringify(input) });
  },

  updateSkill(id, input: AiSkillUpdate) {
    return apiFetch<AiSkill>(`/ai/skills/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  removeSkill(id) {
    return apiFetch<void>(`/ai/skills/${id}`, { method: 'DELETE' });
  },

  listSkillVersions(skillId) {
    return apiFetch<AiSkillVersion[]>(`/ai/skills/${skillId}/versions`);
  },

  rollbackSkill(skillId, versionId) {
    return apiFetch<AiSkill>(`/ai/skills/${skillId}/rollback`, {
      method: 'POST',
      body: JSON.stringify({ versionId }),
    });
  },

  exportSkills(query, columns) {
    return apiFetchText(`/ai/skills/export?${exportParams(query, columns).toString()}`);
  },

  // ── traces ────────────────────────────────────────────────────────────
  listTraces(query) {
    return apiFetch<ListResult<AiTrace>>(`/ai/traces?${listParams(query).toString()}`);
  },

  getTrace(id) {
    return apiFetch<AiTraceDetail>(`/ai/traces/${id}`).catch(() => null);
  },

  flagTrace(id, flagged) {
    return apiFetch<AiTrace>(`/ai/traces/${id}/flag`, {
      method: 'POST',
      body: JSON.stringify({ flagged }),
    });
  },

  async exportTraces(query, columns) {
    // No bulk export endpoint - render CSV from a large page client-side
    // (the workflow-service precedent). 200 is the endpoint's page_size cap;
    // asking for more 422s.
    const result = await apiFetch<ListResult<AiTrace>>(
      `/ai/traces?${listParams({ ...query, page: 0, pageSize: 200 }).toString()}`,
    );
    const labels: Record<string, string> = {
      created: 'When',
      agentName: 'Agent',
      model: 'Model',
      provider: 'Provider',
      status: 'Status',
      tokensIn: 'Tokens in',
      tokensOut: 'Tokens out',
      latencyMs: 'Latency (ms)',
      flagged: 'Flagged',
      error: 'Error',
    };
    const cell = (trace: AiTrace, column: string): string | number => {
      if (column === 'created') return trace.createdAt ?? '';
      if (column === 'flagged') return trace.flagged ? 'Yes' : 'No';
      const value = (trace as unknown as Record<string, unknown>)[column];
      return value === null || value === undefined ? '' : String(value);
    };
    return toCsv(
      columns.map((c) => labels[c] ?? c),
      result.data.map((trace) => columns.map((c) => cell(trace, c))),
    );
  },
};
