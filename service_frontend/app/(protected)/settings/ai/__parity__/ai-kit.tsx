/**
 * Test kit for the AI agents and skills pages: fixed records, a stand-in for
 * `lib/api-client` that answers reads from them and records every write
 * (method, path, body), and a wrapper that renders a page with the Foundryx
 * UIUX switch on or off. Used by the switch-off parity snapshots and by the
 * tests that compare what both looks send.
 */
import type { ReactNode } from 'react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import type {
  AiAgent,
  AiModelList,
  AiPrerequisite,
  AiSkill,
  AiSkillOption,
  AiSkillVersion,
} from '@/types/ai';

export const T0 = '2026-03-04T05:06:07Z';

/** A recognisable prompt body: tests check it never leaks where it is not shown today. */
export const PROMPT = 'You are the business griller.\nAsk one question at a time.\nPROMPT-MARKER-7731';

export const SKILL: AiSkill = {
  id: 's-1',
  key: 'grill-me-business',
  name: 'Business griller',
  description: 'Grills a business idea',
  body: PROMPT,
  activeVersionId: 'v-2',
  activeVersionNumber: 2,
  versionCount: 2,
  isSystem: false,
  isPlatform: false,
  createdAt: T0,
  updatedAt: T0,
};

export const PLATFORM_SKILL: AiSkill = {
  ...SKILL,
  id: 's-9',
  key: 'shared-summary',
  name: 'Shared summary',
  description: 'Provided by the platform',
  body: 'Summarise the thread. PLATFORM-MARKER-2210',
  activeVersionId: 'v-9',
  activeVersionNumber: 1,
  versionCount: 1,
  isPlatform: true,
};

export const SKILLS: AiSkill[] = [SKILL, PLATFORM_SKILL];

export const VERSIONS: AiSkillVersion[] = [
  { id: 'v-2', version: 2, body: PROMPT, isActive: true, createdByName: 'Demo Admin', createdAt: T0 },
  {
    id: 'v-1',
    version: 1,
    body: 'An older prompt. OLD-MARKER-5512',
    isActive: false,
    createdByName: 'Demo Admin',
    createdAt: T0,
  },
];

export const AGENT: AiAgent = {
  id: 'a-1',
  name: 'Griller',
  description: 'Asks hard questions',
  connectionId: 'c-1',
  connectionName: 'OpenRouter',
  provider: 'openrouter',
  model: 'anthropic/claude-sonnet',
  temperature: 0.3,
  skills: [{ id: 's-1', name: 'Business griller' }],
  isEnabled: true,
  warning: null,
  createdAt: T0,
  updatedAt: T0,
};

export const AGENTS: AiAgent[] = [
  AGENT,
  {
    ...AGENT,
    id: 'a-2',
    name: 'Summariser',
    description: 'Summarises',
    connectionId: null,
    connectionName: null,
    provider: null,
    model: '',
    skills: [],
    isEnabled: false,
    warning: 'No connection is set.',
  },
];

export const PREREQ: AiPrerequisite = {
  hasConnection: true,
  connections: [
    { id: 'c-1', name: 'OpenRouter', provider: 'openrouter', status: 'active', isPlatform: false },
    { id: 'c-2', name: 'Shared', provider: 'openai', status: 'active', isPlatform: true },
  ],
};

export const SKILL_OPTIONS: AiSkillOption[] = [
  { id: 's-1', name: 'Business griller' },
  { id: 's-9', name: 'Shared summary' },
];

export const MODELS: Record<string, AiModelList> = {
  'c-1': {
    data: [
      { id: 'anthropic/claude-sonnet', label: 'Claude Sonnet' },
      { id: 'openai/gpt-mini', label: 'GPT mini' },
    ],
    isLive: true,
    message: null,
  },
  'c-2': {
    data: [{ id: 'gpt-shared', label: 'Shared GPT' }],
    isLive: false,
    message: null,
  },
};

export interface RecordedWrite {
  method: string;
  path: string;
  body: unknown;
}

/** Writes seen by the stand-in api client, in order. */
export const writes: RecordedWrite[] = [];

function list<T>(data: T[]) {
  return { data, total: data.length, page: 0, pageSize: 50 };
}

/** Answers a read from the fixtures above. */
function read(path: string): unknown {
  const [p, qs = ''] = path.split('?');
  const q = new URLSearchParams(qs);
  if (p === '/ai/agents') return list(AGENTS);
  if (p === '/ai/agents/at') return { agent: AGENTS[Number(q.get('index') ?? 0)] ?? null, total: AGENTS.length };
  if (p === '/ai/agents/prerequisite') return PREREQ;
  if (p === '/ai/agents/skill-options') return SKILL_OPTIONS;
  if (p === '/ai/agents/models') return MODELS[q.get('connection_id') ?? ''] ?? { data: [], isLive: true, message: null };
  const agent = AGENTS.find((a) => p === `/ai/agents/${a.id}`);
  if (agent) return agent;
  if (p === '/ai/skills') return list(SKILLS);
  if (p === '/ai/skills/at') return { skill: SKILLS[Number(q.get('index') ?? 0)] ?? null, total: SKILLS.length };
  if (SKILLS.some((s) => p === `/ai/skills/${s.id}/versions`)) return VERSIONS;
  const skill = SKILLS.find((s) => p === `/ai/skills/${s.id}`);
  if (skill) return skill;
  return null;
}

/** What a write answers with. */
function answer(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path === '/ai/agents' && method === 'POST') return { ...AGENT, id: 'a-new', name: String(b.name) };
  if (path.startsWith('/ai/agents/') && method === 'PATCH') return { ...AGENT, name: String(b.name ?? AGENT.name) };
  if (path === '/ai/skills' && method === 'POST') return { ...SKILL, id: 's-new', name: String(b.name) };
  if (path === `/ai/skills/${PLATFORM_SKILL.id}` && method === 'PATCH') {
    return { ...SKILL, id: 's-fork', name: String(b.name ?? SKILL.name) };
  }
  if (path.startsWith('/ai/skills/') && path.endsWith('/rollback')) return { ...SKILL, activeVersionNumber: 1 };
  if (path.startsWith('/ai/skills/') && method === 'PATCH') {
    return { ...SKILL, name: String(b.name ?? SKILL.name), activeVersionNumber: 3 };
  }
  return null;
}

/** The `apiFetch` stand-in: reads from fixtures, records every write. */
export async function fakeApiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? 'GET').toUpperCase();
  if (method === 'GET') return read(path);
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : (init.body ?? null);
  writes.push({ method, path, body });
  return answer(method, path, body);
}

/** Renders `children` with the switch on (`fx`) or off. */
export function Look({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>{children}</TooltipsProvider>
    </FxProvider>
  );
}

/**
 * React 19 ids (`_r_7f_`) renamed in order of first appearance, and the
 * mid-animation inline style a closing Radix tab panel may still carry
 * dropped (it depends on timing, not on the markup).
 */
export function maskIds(html: string): string {
  const seen = new Map<string, string>();
  const still = html.replace(/ style="animation-duration: 0s;"/g, ' style=""');
  return still.replace(/_r_[0-9a-z]+_/g, (id) => {
    let stable = seen.get(id);
    if (!stable) {
      stable = `_rid${seen.size}_`;
      seen.set(id, stable);
    }
    return stable;
  });
}
