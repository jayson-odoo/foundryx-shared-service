/**
 * In-memory AI service - **TEST FIXTURE ONLY, not a shipped mock.**
 *
 * The slice ships real-bound (`ai-service.ts` → `ai-service.real`); this module
 * exists so Vitest can drive the list/form configs without a backend. It is
 * deliberately NOT wired into the app: a mock reaching a user-perspective QA
 * pass is the failure mode this project has repeatedly paid for.
 */
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

function nowIso(): string {
  return new Date().toISOString();
}

export function makeAgent(overrides: Partial<AiAgent> = {}): AiAgent {
  return {
    id: 'agent-1',
    name: 'Business griller',
    description: 'Turns ideas into business requirements.',
    connectionId: 'conn-1',
    connectionName: 'Gemini key',
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    temperature: 0,
    skills: [{ id: 'skill-1', name: 'grill-me-business' }],
    isEnabled: true,
    warning: null,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    ...overrides,
  };
}

export function makeSkill(overrides: Partial<AiSkill> = {}): AiSkill {
  return {
    id: 'skill-1',
    key: 'grill-me-business',
    name: 'Grill me (business)',
    description: 'Clarifying conversation toward a business requirement.',
    body: 'Ground every answer in the linked ideas.',
    activeVersionId: 'ver-1',
    activeVersionNumber: 1,
    versionCount: 1,
    isSystem: false,
    isPlatform: false,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    ...overrides,
  };
}

export function makeTrace(overrides: Partial<AiTrace> = {}): AiTrace {
  return {
    id: 'trace-1',
    conversationId: null,
    agentId: 'agent-1',
    agentName: 'Business griller',
    skillKey: 'grill-me-business',
    promptVersion: 1,
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    tokensIn: 120,
    tokensOut: 40,
    latencyMs: 850,
    status: 'ok',
    error: null,
    flagged: false,
    spanCount: 1,
    createdAt: nowIso(),
    ...overrides,
  };
}

function page<T>(rows: T[], query: ListQuery): ListResult<T> {
  const start = query.page * query.pageSize;
  return { data: rows.slice(start, start + query.pageSize), total: rows.length, page: query.page };
}

const agents: AiAgent[] = [makeAgent()];
const skills: AiSkill[] = [makeSkill()];
const traces: AiTrace[] = [makeTrace()];

export const mockAiService: AiService = {
  listAgents: async (query) => page(agents, query),
  getAgentAt: async (_query, index) => ({ agent: agents[index] ?? null, total: agents.length }),
  getAgent: async (id) => agents.find((a) => a.id === id) ?? null,
  createAgent: async (input: AiAgentInput) => makeAgent({ ...input, id: `agent-${agents.length + 1}` }),
  updateAgent: async (id, input: AiAgentInput) => makeAgent({ ...input, id }),
  removeAgent: async () => undefined,
  exportAgents: async () => 'Name,Model\nBusiness griller,gemini-2.5-flash\n',

  getPrerequisite: async (): Promise<AiPrerequisite> => ({
    hasConnection: true,
    connections: [
      { id: 'conn-1', name: 'Gemini key', provider: 'gemini', status: 'ACTIVE', isPlatform: false },
    ],
  }),
  listModels: async (): Promise<AiModelList> => ({
    data: [
      { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
      { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
    ],
    isLive: true,
    message: null,
  }),
  listSkillOptions: async (): Promise<AiSkillOption[]> => [
    { id: 'skill-1', name: 'Grill me (business)' },
  ],

  listSkills: async (query) => page(skills, query),
  getSkillAt: async (_query, index) => ({ skill: skills[index] ?? null, total: skills.length }),
  getSkill: async (id) => skills.find((s) => s.id === id) ?? null,
  createSkill: async (input: AiSkillInput) => makeSkill({ ...input, id: `skill-${skills.length + 1}` }),
  updateSkill: async (id, input: AiSkillUpdate) => makeSkill({ ...input, id }),
  removeSkill: async () => undefined,
  listSkillVersions: async (): Promise<AiSkillVersion[]> => [
    {
      id: 'ver-1',
      version: 1,
      body: 'Ground every answer in the linked ideas.',
      isActive: true,
      createdByName: 'Demo User',
      createdAt: nowIso(),
    },
  ],
  rollbackSkill: async (skillId) => makeSkill({ id: skillId }),
  exportSkills: async () => 'Key,Name\ngrill-me-business,Grill me (business)\n',

  listTraces: async (query) => page(traces, query),
  getTrace: async (id): Promise<AiTraceDetail | null> => ({
    ...makeTrace({ id }),
    spans: [
      {
        id: 'span-1',
        parentId: null,
        dottedOrder: '1',
        spanKind: 'llm_call',
        name: 'completion',
        inputJson: { system: 'be helpful', messages: [] },
        outputJson: { text: 'hello' },
        tokensIn: 120,
        tokensOut: 40,
        latencyMs: 850,
        status: 'ok',
        error: null,
        startedAt: nowIso(),
      },
    ],
  }),
  flagTrace: async (id, flagged) => makeTrace({ id, flagged }),
  exportTraces: async () => 'When,Agent\n2026-07-21,Business griller\n',
};
