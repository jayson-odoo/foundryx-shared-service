/**
 * W4-AI, AI agents and skills, with the Foundryx UIUX switch on.
 *
 * Core guarantee: every request these pages send is the same in both looks
 * for the same input, byte for byte: agent create and edit (name, connection,
 * model, temperature, the equipped skills, enabled), agent and skill delete,
 * skill create and edit (the prompt text exactly as typed), editing a
 * provided skill, and making an older version active.
 *
 * Prompt text: never put anywhere it is not shown today (labels, toasts,
 * browser storage, the console) and never made copyable. Permissions:
 * neither look shows more to a user than today.
 */
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { toast } from '@/lib/toast';
import AiAgentsPage from '../agents/page';
import AiSkillsPage from '../skills/page';
import AgentFormPage from '../agents/[id]/page';
import SkillFormPage from '../skills/[id]/page';
import { AgentFormView } from '../components/agent-form-view';
import { SkillFormView } from '../components/skill-form-view';
import { Look, PROMPT, writes, type RecordedWrite } from './ai-kit';

const nav = vi.hoisted(() => ({ path: '/settings/ai/agents' }));
const perms = vi.hoisted(() => [] as string[]);
const spies = vi.hoisted(() => ({ deferredStart: [] as unknown[][] }));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ id: 'a-1' })),
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
  useDeferredAction: () => ({
    state: { status: 'idle' },
    start: async (...args: unknown[]) => {
      spies.deferredStart.push(args);
      return {};
    },
    cancel: vi.fn(),
  }),
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

beforeEach(() => {
  perms.splice(0, perms.length, 'ai_agents.read', 'ai_agents.manage');
});

afterEach(() => {
  cleanup();
  writes.length = 0;
  spies.deferredStart.length = 0;
  resetPageActionsForTests();
  document.body.innerHTML = '';
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

type Ui = ReturnType<typeof userEvent.setup>;

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

async function mount(fx: boolean, path: string, ui: React.ReactElement, ready: (doc: HTMLElement) => boolean) {
  nav.path = path;
  let unmount!: () => void;
  await act(async () => {
    unmount = render(<Look fx={fx}>{ui}</Look>).unmount;
  });
  await waitFor(() => expect(ready(document.body)).toBe(true));
  await settle();
  return unmount;
}

const text = (t: string) => (doc: HTMLElement) => doc.textContent?.includes(t) ?? false;
const field = (doc: HTMLElement) => doc.querySelector('input, textarea') !== null;

interface Sent {
  writes: RecordedWrite[];
  deferred: unknown[][];
}

async function sent(
  fx: boolean,
  path: string,
  ui: React.ReactElement,
  ready: (doc: HTMLElement) => boolean,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<Sent> {
  writes.length = 0;
  spies.deferredStart.length = 0;
  const u = userEvent.setup();
  const unmount = await mount(fx, path, ui, ready);
  await steps(u, fx);
  await settle();
  const out = { writes: writes.map((w) => ({ ...w })), deferred: spies.deferredStart.map((a) => [...a]) };
  unmount();
  resetPageActionsForTests();
  document.body.innerHTML = '';
  return out;
}

/** The same steps in both looks: the requests (and parked actions) must match, and not be empty. */
async function bothLooks(
  path: string,
  ui: () => React.ReactElement,
  ready: (doc: HTMLElement) => boolean,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<Sent> {
  const off = await sent(false, path, ui(), ready, steps);
  const on = await sent(true, path, ui(), ready, steps);
  expect(off.writes.length + off.deferred.length).toBeGreaterThan(0);
  expect(on).toEqual(off);
  // Byte for byte: the serialised bodies are the same strings.
  expect(on.writes.map((w) => JSON.stringify(w.body))).toEqual(off.writes.map((w) => JSON.stringify(w.body)));
  return off;
}

const redAction = () => document.querySelector<HTMLElement>('[data-fx-main-action] button');

async function save(u: Ui, fx: boolean, offLabel: RegExp) {
  if (fx) {
    expect(redAction()).not.toBeNull();
    await u.click(redAction()!);
  } else {
    await u.click(screen.getByRole('button', { name: offLabel }));
  }
  await settle();
}

async function pick(u: Ui, combo: HTMLElement, names: string[]) {
  await u.click(combo);
  for (const name of names) await u.click(await screen.findByRole('option', { name }));
  await u.keyboard('{Escape}');
}

/** The skills picker: named "Skills" while on; the one unnamed combobox while off. */
function skillsCombo(): HTMLElement {
  const named = screen.queryByRole('combobox', { name: 'Skills' });
  if (named) return named;
  const all = screen.getAllByRole('combobox');
  const rest = all.filter((c) => !['Connection', 'Model'].includes(c.getAttribute('aria-label') ?? ''));
  return rest[rest.length - 1];
}

async function typeInto(u: Ui, el: HTMLElement, value: string) {
  await u.clear(el);
  if (value) await u.type(el, value);
}

const AGENT_NEW = () => <AgentFormView initialEditing />;
const AGENT_EDIT = () => <AgentFormView agentId="a-1" initialEditing />;
const AGENT_READ = () => <AgentFormView agentId="a-1" initialEditing={false} />;
const SKILL_NEW = () => <SkillFormView initialEditing />;
const SKILL_EDIT = () => <SkillFormView skillId="s-1" initialEditing />;
const SKILL_READ = () => <SkillFormView skillId="s-1" initialEditing={false} />;

/** Prompt text with characters a careless rewrite would change. */
const TYPED_PROMPT = 'Line one: "quoted" & <tag>\n\tIndented, trailing space \nLast line ending a91c';

describe('AI agents and skills: the same requests in both looks', () => {
  it('creates an agent with a connection, model, temperature and skills', async () => {
    const out = await bothLooks('/settings/ai/agents/new', AGENT_NEW, text('New agent'), async (u, fx) => {
      await typeInto(u, screen.getByPlaceholderText('e.g. Business griller'), '  Closer  ');
      await typeInto(u, document.querySelector('textarea')!, ' Closes deals ');
      await pick(u, screen.getByRole('combobox', { name: 'Connection' }), ['OpenRouter']);
      await waitFor(() => expect(screen.getByRole('combobox', { name: 'Model' })).not.toBeDisabled());
      await pick(u, screen.getByRole('combobox', { name: 'Model' }), ['GPT mini']);
      await typeInto(u, document.querySelector<HTMLElement>('input[type=number]')!, '0.7');
      await pick(u, skillsCombo(), ['Business griller', 'Shared summary']);
      await u.click(screen.getByRole('switch'));
      await save(u, fx, /^Save/);
    });
    expect(out.writes).toEqual([
      {
        method: 'POST',
        path: '/ai/agents',
        body: {
          name: 'Closer',
          description: 'Closes deals',
          connectionId: 'c-1',
          model: 'openai/gpt-mini',
          temperature: 0.7,
          skillIds: ['s-1', 's-9'],
          isEnabled: false,
        },
      },
    ]);
  });

  it('edits an agent: model, temperature and skills', async () => {
    const out = await bothLooks('/settings/ai/agents/a-1', AGENT_EDIT, text('Claude Sonnet'), async (u, fx) => {
      await pick(u, screen.getByRole('combobox', { name: 'Model' }), ['GPT mini']);
      await typeInto(u, document.querySelector<HTMLElement>('input[type=number]')!, '1.25');
      await pick(u, skillsCombo(), ['Shared summary']);
      await save(u, fx, /^Save/);
    });
    expect(out.writes[0]).toMatchObject({
      method: 'PATCH',
      path: '/ai/agents/a-1',
      body: { model: 'openai/gpt-mini', temperature: 1.25, skillIds: ['s-1', 's-9'] },
    });
  });

  it('deletes an agent through the same grace window', async () => {
    const out = await bothLooks('/settings/ai/agents/a-1', AGENT_READ, text('anthropic/claude-sonnet'), async (u, fx) => {
      if (fx) {
        await u.click(screen.getByRole('button', { name: 'Delete' }));
      } else {
        await u.click(screen.getByRole('button', { name: 'Actions' }));
        await u.click(await screen.findByRole('menuitem', { name: 'Delete' }));
      }
    });
    expect(out.deferred[0]?.[0]).toBe('ai_agents.delete');
  });

  it('creates a skill with the prompt exactly as typed', async () => {
    const out = await bothLooks('/settings/ai/skills/new', SKILL_NEW, text('New skill'), async (u, fx) => {
      await typeInto(u, screen.getByPlaceholderText('e.g. grill-me-business'), 'closer');
      const inputs = Array.from(document.querySelectorAll<HTMLInputElement>('input:not([type=checkbox])'));
      await typeInto(u, inputs[1], 'Closer');
      const areas = document.querySelectorAll('textarea');
      await typeInto(u, areas[0], 'Closes');
      await u.click(areas[1]);
      await u.paste(TYPED_PROMPT);
      await save(u, fx, /^Save/);
    });
    expect(out.writes).toEqual([
      {
        method: 'POST',
        path: '/ai/skills',
        body: { key: 'closer', name: 'Closer', description: 'Closes', body: TYPED_PROMPT },
      },
    ]);
  });

  it('edits a skill prompt', async () => {
    const out = await bothLooks('/settings/ai/skills/s-1', SKILL_EDIT, field, async (u, fx) => {
      const areas = document.querySelectorAll('textarea');
      await u.clear(areas[1]);
      await u.click(areas[1]);
      await u.paste(TYPED_PROMPT);
      await save(u, fx, /^Save/);
    });
    expect(out.writes[0]).toMatchObject({ method: 'PATCH', path: '/ai/skills/s-1', body: { body: TYPED_PROMPT } });
  });

  it('editing a provided skill sends the same request', async () => {
    await bothLooks(
      '/settings/ai/skills/s-9',
      () => <SkillFormView skillId="s-9" initialEditing />,
      field,
      async (u, fx) => {
        const name = Array.from(document.querySelectorAll<HTMLInputElement>('input')).find((i) => i.value === 'Shared summary')!;
        await typeInto(u, name, 'My summary');
        await save(u, fx, /^Save/);
      },
    );
  });

  it('deletes a skill through the same grace window', async () => {
    const out = await bothLooks('/settings/ai/skills/s-1', SKILL_READ, text('PROMPT-MARKER-7731'), async (u, fx) => {
      if (fx) {
        await u.click(screen.getByRole('button', { name: 'Delete' }));
      } else {
        await u.click(screen.getByRole('button', { name: 'Actions' }));
        await u.click(await screen.findByRole('menuitem', { name: 'Delete' }));
      }
    });
    expect(out.deferred[0]?.[0]).toBe('ai_skills.delete');
  });

  it('makes an older version active', async () => {
    const out = await bothLooks('/settings/ai/skills/s-1', SKILL_READ, text('PROMPT-MARKER-7731'), async (u) => {
      vi.spyOn(toast, 'fxDone').mockReturnValue(0);
      vi.spyOn(toast, 'success').mockReturnValue(0);
      await u.click(screen.getByRole('tab', { name: 'Versions' }));
      await u.click(await screen.findByRole('button', { name: /Make active/ }));
    });
    expect(out.writes).toEqual([{ method: 'POST', path: '/ai/skills/s-1/rollback', body: { versionId: 'v-1' } }]);
  });
});

describe('AI skills: the prompt stays where it is shown today', () => {
  it('a saved prompt is never logged, stored, toasted or put in a label (switch on)', async () => {
    const logs = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => {}),
    );
    const toasts = [
      vi.spyOn(toast, 'fxDone').mockReturnValue(0),
      vi.spyOn(toast, 'success').mockReturnValue(0),
      vi.spyOn(toast, 'error').mockReturnValue(0),
    ];
    const u = userEvent.setup();
    await mount(true, '/settings/ai/skills/s-1', SKILL_EDIT(), field);
    const red = redAction()!;
    expect(red.outerHTML).not.toContain('PROMPT-MARKER');
    const areas = document.querySelectorAll('textarea');
    await u.clear(areas[1]);
    await u.click(areas[1]);
    await u.paste(`${PROMPT} NEW-MARKER-4410`);
    await save(u, true, /^Save/);
    expect(writes.at(-1)?.body).toMatchObject({ body: `${PROMPT} NEW-MARKER-4410` });
    for (const spy of [...logs, ...toasts]) {
      const calls = JSON.stringify(spy.mock.calls);
      expect(calls).not.toContain('PROMPT-MARKER');
      expect(calls).not.toContain('NEW-MARKER');
    }
    const stored = [localStorage, sessionStorage].flatMap((s) => Object.keys(s).map((k) => `${k}=${s.getItem(k)}`));
    expect(stored.join('\n')).not.toMatch(/PROMPT-MARKER|NEW-MARKER/);
    // Every label and tooltip on the page leaves the prompt out.
    for (const el of Array.from(document.querySelectorAll('[aria-label], [title]'))) {
      expect(`${el.getAttribute('aria-label')} ${el.getAttribute('title')}`).not.toMatch(/PROMPT-MARKER|NEW-MARKER/);
    }
  });

  it('the prompt and older versions are not copyable by Hold to Copy (switch on)', async () => {
    const u = userEvent.setup();
    await mount(true, '/settings/ai/skills/s-1', SKILL_READ(), text('PROMPT-MARKER-7731'));
    // Plain values such as the name are Hold to Copy; the prompt is not.
    const copyable = () => Array.from(document.querySelectorAll('[data-fx-h2c]')).map((e) => e.textContent ?? '');
    expect(copyable()).toContain('Business griller');
    expect(copyable().join('|')).not.toMatch(/MARKER/);
    await u.click(screen.getByRole('tab', { name: 'Versions' }));
    await waitFor(() => expect(document.body.textContent).toContain('OLD-MARKER-5512'));
    expect(copyable().join('|')).not.toMatch(/MARKER/);
  });

  it('the skills list never shows a prompt (switch on)', async () => {
    await mount(true, '/settings/ai/skills', <AiSkillsPage />, text('Shared summary'));
    expect(document.body.innerHTML).not.toMatch(/PROMPT-MARKER|PLATFORM-MARKER|OLD-MARKER/);
  });

  it('making a version active offers Undo, which makes the earlier one active again', async () => {
    const done = vi.spyOn(toast, 'fxDone').mockReturnValue(0);
    const u = userEvent.setup();
    await mount(true, '/settings/ai/skills/s-1', SKILL_READ(), text('PROMPT-MARKER-7731'));
    await u.click(screen.getByRole('tab', { name: 'Versions' }));
    await u.click(await screen.findByRole('button', { name: /Make active/ }));
    await settle();
    const input = done.mock.calls[0][0];
    expect(input.what).toBe('Version 1 is now active');
    expect(JSON.stringify(input)).not.toMatch(/MARKER/);
    await act(async () => {
      input.undo!();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(writes).toEqual([
      { method: 'POST', path: '/ai/skills/s-1/rollback', body: { versionId: 'v-1' } },
      { method: 'POST', path: '/ai/skills/s-1/rollback', body: { versionId: 'v-2' } },
    ]);
  });
});

describe('AI agents and skills: who sees what is the same in both looks', () => {
  it.each([false, true])('without ai_agents.read every page shows no access (switch %s)', async (fx) => {
    perms.splice(0, perms.length, 'ai_agents.manage');
    for (const ui of [<AiAgentsPage key="a" />, <AiSkillsPage key="b" />, <AgentFormPage key="c" />, <SkillFormPage key="d" />]) {
      const unmount = await mount(fx, '/settings/ai/agents', ui, text('have access'));
      expect(redAction()).toBeNull();
      unmount();
      resetPageActionsForTests();
      document.body.innerHTML = '';
    }
    expect(writes).toEqual([]);
  });

  it.each([false, true])('a read-only user gets no create, edit, delete or Make active (switch %s)', async (fx) => {
    perms.splice(0, perms.length, 'ai_agents.read');
    const u = userEvent.setup();
    let unmount = await mount(fx, '/settings/ai/agents', <AiAgentsPage />, text('Summariser'));
    expect(screen.queryByRole('button', { name: /New agent/ })).toBeNull();
    expect(redAction()).toBeNull();
    unmount();
    resetPageActionsForTests();
    document.body.innerHTML = '';

    unmount = await mount(fx, '/settings/ai/agents/a-1', AGENT_READ(), text('anthropic/claude-sonnet'));
    expect(redAction()).toBeNull();
    expect(screen.queryByRole('button', { name: /^Edit/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Actions' })).toBeNull();
    unmount();
    resetPageActionsForTests();
    document.body.innerHTML = '';

    unmount = await mount(fx, '/settings/ai/skills/s-1', SKILL_READ(), text('PROMPT-MARKER-7731'));
    expect(redAction()).toBeNull();
    expect(screen.queryByRole('button', { name: /^Edit/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    await u.click(screen.getByRole('tab', { name: 'Versions' }));
    await waitFor(() => expect(document.body.textContent).toContain('OLD-MARKER-5512'));
    expect(screen.queryByRole('button', { name: /Make active/ })).toBeNull();
    unmount();
  });
});

describe('AI agents and skills under the new look', () => {
  it('a record page has Edit as its red action at rest and Save while editing', async () => {
    const u = userEvent.setup();
    await mount(true, '/settings/ai/agents/a-1', AGENT_READ(), text('anthropic/claude-sonnet'));
    expect(redAction()?.textContent).toMatch(/Edit/);
    await u.click(redAction()!);
    await waitFor(() => expect(redAction()?.textContent).toMatch(/Save/));
    expect(within(document.body).getByRole('combobox', { name: 'Skills' })).toBeTruthy();
  });
});
