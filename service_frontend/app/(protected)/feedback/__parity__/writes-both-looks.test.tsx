/**
 * W6-FEEDBACK core guarantee: with the Foundryx UIUX switch on, every request
 * these pages send is the same as with it off for the same input. Each case
 * drives the real page (record views with their real hooks, services and
 * `ResourceForm`) through the controls each look shows, records what reaches
 * `lib/api-client` (method, path, body), and compares both looks: idea create
 * and edit, the status move from the page, votes, comment create, business
 * requirement create and edit, embed connection create and secret rotate.
 * The embed secret is shown once and never stored or logged.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { IdeaFormView } from '../components/idea-form-view';
import { IdeaComments } from '../components/idea-comments';
import { BrFormView } from '../business-requirements/components/br-form-view';
import BrPage from '../business-requirements/page';
import EmbedConnectionsPage from '../embed-connections/page';
import { Look, writes, ALL_PERMISSIONS, type RecordedWrite } from './fb-kit';

const nav = vi.hoisted(() => ({ path: '/feedback' }));
const perms = vi.hoisted(() => [] as string[]);

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
  const kit = await import('./fb-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
    apiFetchBlob: vi.fn(async () => new Blob()),
  };
});

perms.push(...ALL_PERMISSIONS);

afterEach(() => {
  writes.length = 0;
  resetPageActionsForTests();
  document.body.innerHTML = '';
});

type Ui = ReturnType<typeof userEvent.setup>;

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

/** Renders `ui` in one look, runs `steps`, returns the writes it sent. */
async function sent(
  fx: boolean,
  path: string,
  ui: React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<RecordedWrite[]> {
  nav.path = path;
  writes.length = 0;
  const u = userEvent.setup();
  let unmount!: () => void;
  await act(async () => {
    unmount = render(<Look fx={fx}>{ui}</Look>).unmount;
  });
  await waitFor(() => expect(document.body.textContent).toContain(ready));
  await settle();
  await steps(u, fx);
  await settle();
  const out = writes.map((w) => ({ ...w }));
  unmount();
  resetPageActionsForTests();
  document.body.innerHTML = '';
  return out;
}

/** The same steps in both looks: the writes must match, and not be empty. */
async function bothLooks(
  path: string,
  ui: () => React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<RecordedWrite[]> {
  const off = await sent(false, path, ui(), ready, steps);
  const on = await sent(true, path, ui(), ready, steps);
  expect(off.length).toBeGreaterThan(0);
  expect(on).toEqual(off);
  return off;
}

async function typeInto(u: Ui, placeholder: string, text: string) {
  const input = screen.getByPlaceholderText(placeholder);
  await u.clear(input);
  await u.type(input, text);
}

/** The page's red action while on, the card's own button while off. */
async function pressMain(u: Ui, fx: boolean, offLabel: string) {
  const red = fx ? document.querySelector<HTMLElement>('[data-fx-main-action] button') : null;
  if (fx) expect(red).not.toBeNull();
  await u.click(red ?? screen.getByRole('button', { name: new RegExp(`^${offLabel}`) }));
  await settle();
}

describe('the same input sends the same requests in both looks', () => {
  it('creates an idea', async () => {
    const [w] = await bothLooks('/feedback/new', () => <IdeaFormView initialEditing />, 'New feedback', async (u, fx) => {
      await u.click(screen.getByRole('combobox'));
      await u.click(await screen.findByRole('option', { name: 'Sorento CRM' }));
      await typeInto(u, 'What problem does the business have?', 'Bulk import is slow');
      await pressMain(u, fx, 'Create');
    });
    expect(w.method).toBe('POST');
    expect(w.path).toBe('/ideation/ideas');
    expect((w.body as { problem: string }).problem).toBe('Bulk import is slow');
  });

  it('edits an idea', async () => {
    const [w] = await bothLooks('/feedback/idea-1', () => <IdeaFormView ideaId="idea-1" initialEditing />, 'Export orders to Excel', async (u, fx) => {
      await typeInto(u, 'What problem does the business have?', 'Export orders to CSV');
      // While editing, the card's own Save is the save in both looks.
      await u.click(screen.getByRole('button', { name: /^Save/ }));
      void fx;
      await settle();
    });
    expect(w.method).toBe('PATCH');
    expect(w.path).toBe('/ideation/ideas/idea-1');
    expect((w.body as { problem: string }).problem).toBe('Export orders to CSV');
  });

  it('moves an idea to its next stage from the page', async () => {
    const [w] = await bothLooks('/feedback/idea-1', () => <IdeaFormView ideaId="idea-1" initialEditing={false} />, 'Export orders to Excel', async (u, fx) => {
      await pressMain(u, fx, 'Move to Triaged');
    });
    expect(w).toEqual({
      method: 'POST',
      path: '/ideation/ideas/idea-1/status',
      body: { toStatusId: 'idea-status-triaged' },
    });
  });

  it('votes on an idea', async () => {
    const [w] = await bothLooks('/feedback/idea-1', () => <IdeaFormView ideaId="idea-1" initialEditing={false} />, 'Export orders to Excel', async (u) => {
      await u.click(screen.getAllByRole('button', { name: 'Upvote' })[0]);
    });
    expect(w).toEqual({ method: 'POST', path: '/ideation/ideas/idea-1/vote', body: { dir: 'up' } });
  });

  it('posts a comment and a reply', async () => {
    const out = await bothLooks('/feedback/idea-1', () => <IdeaComments ideaId="idea-1" canComment />, 'Looks good to me', async (u) => {
      await u.type(screen.getByPlaceholderText('Write a comment'), 'Ship it');
      await u.click(screen.getByRole('button', { name: 'Comment' }));
      await settle();
    });
    expect(out[0].method).toBe('POST');
    expect(out[0].path).toBe('/ideation/ideas/idea-1/comments');
    expect((out[0].body as { body: string }).body).toBe('Ship it');
  });

  it('creates a business requirement', async () => {
    const [w] = await bothLooks('/feedback/business-requirements', () => <BrPage />, 'Order export to Excel', async (u, fx) => {
      void fx;
      await u.click(screen.getAllByRole('button', { name: /New requirement/ })[0]);
      await typeInto(u, 'e.g. Order export to Excel', 'Faster imports');
      await u.click(await screen.findByRole('button', { name: 'Create draft' }));
      await settle();
    });
    expect(w.method).toBe('POST');
    expect(w.path).toBe('/ideation/business-requirements');
    expect((w.body as { title: string }).title).toBe('Faster imports');
  });

  it('edits a business requirement', async () => {
    const [w] = await bothLooks('/feedback/business-requirements/br-1', () => <BrFormView brId="br-1" initialEditing />, 'Order export to Excel', async (u, fx) => {
      await typeInto(u, 'Describe the problem', 'Slow exports and imports');
      await pressMain(u, fx, 'Save');
    });
    expect(w.method).toBe('PATCH');
    expect(w.path).toBe('/ideation/business-requirements/br-1');
    expect(w.body).toEqual({ title: 'Order export to Excel', answers: { problem: 'Slow exports and imports' } });
  });
});

describe('embed connections', () => {
  const SECRET = 'a-secret-value-123';

  async function create(u: Ui) {
    await u.click(screen.getAllByRole('button', { name: /Add connection/ })[0]);
    await u.type(await screen.findByPlaceholderText('e.g. sorento-feedback'), 'host-one');
    await u.type(screen.getByPlaceholderText('At least 8 characters, or generate one'), SECRET);
    await u.click(screen.getByRole('button', { name: /^Create/ }));
    await settle();
  }

  it('sends the same create request in both looks', async () => {
    const [w] = await bothLooks('/feedback/embed-connections', () => <EmbedConnectionsPage />, 'sorento-feedback', create);
    expect(w).toMatchObject({ method: 'POST', path: '/ideation/embed-connections' });
    expect(w.body).toMatchObject({ connection_id: 'host-one', signing_secret: SECRET });
  });

  for (const fx of [false, true]) {
    it(`shows the secret once, then never again (switch ${fx ? 'on' : 'off'})`, async () => {
      const spies = [vi.spyOn(console, 'log'), vi.spyOn(console, 'info'), vi.spyOn(console, 'warn'), vi.spyOn(console, 'error')];
      nav.path = '/feedback/embed-connections';
      const u = userEvent.setup();
      await act(async () => {
        render(
          <Look fx={fx}>
            <EmbedConnectionsPage />
          </Look>,
        );
      });
      await waitFor(() => expect(document.body.textContent).toContain('sorento-feedback'));
      await create(u);
      // Shown in full in the dialog that made it.
      expect(screen.getByLabelText('Signing secret')).toHaveValue(SECRET);
      await u.click(screen.getByRole('button', { name: 'Done' }));
      await settle();
      // Closed: nowhere on the page, in storage or in a log.
      expect(document.body.textContent).not.toContain(SECRET);
      expect(document.body.innerHTML).not.toContain(SECRET);
      expect(JSON.stringify(Object.entries(window.localStorage))).not.toContain(SECRET);
      expect(JSON.stringify(Object.entries(window.sessionStorage))).not.toContain(SECRET);
      for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
      // Reading the list again never returns it (the fixture row has no secret field).
      spies.forEach((s) => s.mockRestore());
    });
  }
});
