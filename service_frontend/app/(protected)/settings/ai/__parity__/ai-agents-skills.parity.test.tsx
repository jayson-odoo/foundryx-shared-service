/**
 * Switch-off parity for the AI agents and skills pages (see
 * components/fx/__parity__/parity-utils.ts). Recorded on the code before the
 * W4-AI slice: both lists, each record read and editing, each new form and
 * a skill's Versions tab, rendered with the Foundryx UIUX switch off. A
 * change that needs one of these snapshots updated changes what a user sees
 * today: fix the code, never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import AiAgentsPage from '../agents/page';
import AiSkillsPage from '../skills/page';
import { AgentFormView } from '../components/agent-form-view';
import { SkillFormView } from '../components/skill-form-view';
import { Look, maskIds, writes } from './ai-kit';

const nav = vi.hoisted(() => ({ path: '/settings/ai/agents' }));
const perms = vi.hoisted(() => ['ai_agents.read', 'ai_agents.manage']);

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', name: 'Demo Admin', permissions: perms } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(async () => ({})), cancel: vi.fn() }),
}));
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  const kit = await import('./ai-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
  };
});

afterEach(() => {
  writes.length = 0;
  document.body.innerHTML = '';
});

type Ui = ReturnType<typeof userEvent.setup>;

async function snapOff(
  path: string,
  ui: ReactElement,
  ready: (root: HTMLElement) => boolean,
  steps?: (u: Ui) => Promise<void>,
  readyAfter?: (root: HTMLElement) => boolean,
) {
  nav.path = path;
  const u = userEvent.setup();
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Look fx={false}>{ui}</Look>);
  });
  await waitFor(() => expect(ready(utils.container)).toBe(true));
  if (steps) {
    await steps(u);
    if (readyAfter) await waitFor(() => expect(readyAfter(utils.container)).toBe(true));
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const html = maskIds(parityHtml(utils.container));
  utils.unmount();
  return html;
}

const hasText = (text: string) => (root: HTMLElement) => root.textContent?.includes(text) ?? false;

describe('AI agents and skills switch-off parity', () => {
  it('agents list', async () => {
    expect(await snapOff('/settings/ai/agents', <AiAgentsPage />, hasText('Summariser'))).toMatchSnapshot();
  });

  it('agent record, read', async () => {
    expect(
      await snapOff('/settings/ai/agents/a-1', <AgentFormView agentId="a-1" initialEditing={false} />, hasText('anthropic/claude-sonnet')),
    ).toMatchSnapshot();
  });

  it('agent record, editing', async () => {
    expect(
      await snapOff('/settings/ai/agents/a-1', <AgentFormView agentId="a-1" initialEditing />, hasText('Claude Sonnet')),
    ).toMatchSnapshot();
  });

  it('new agent', async () => {
    expect(await snapOff('/settings/ai/agents/new', <AgentFormView initialEditing />, hasText('New agent'))).toMatchSnapshot();
  });

  it('skills list', async () => {
    expect(await snapOff('/settings/ai/skills', <AiSkillsPage />, hasText('Shared summary'))).toMatchSnapshot();
  });

  it('skill record, read', async () => {
    expect(
      await snapOff('/settings/ai/skills/s-1', <SkillFormView skillId="s-1" initialEditing={false} />, hasText('PROMPT-MARKER-7731')),
    ).toMatchSnapshot();
  });

  it('skill record, editing', async () => {
    expect(
      await snapOff('/settings/ai/skills/s-1', <SkillFormView skillId="s-1" initialEditing />, (r) => r.querySelector('textarea') !== null),
    ).toMatchSnapshot();
  });

  it('provided skill, read', async () => {
    expect(
      await snapOff('/settings/ai/skills/s-9', <SkillFormView skillId="s-9" initialEditing={false} />, hasText('PLATFORM-MARKER-2210')),
    ).toMatchSnapshot();
  });

  it('skill versions tab', async () => {
    expect(
      await snapOff(
        '/settings/ai/skills/s-1',
        <SkillFormView skillId="s-1" initialEditing={false} />,
        hasText('PROMPT-MARKER-7731'),
        async (u) => {
          await u.click(screen.getByRole('tab', { name: 'Versions' }));
        },
        hasText('Make active'),
      ),
    ).toMatchSnapshot();
  });

  it('new skill', async () => {
    expect(await snapOff('/settings/ai/skills/new', <SkillFormView initialEditing />, hasText('New skill'))).toMatchSnapshot();
  });
});
