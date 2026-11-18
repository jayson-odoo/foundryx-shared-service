/**
 * The integrations pages with the Foundryx UIUX switch on (slice W4-TEMPLATES).
 *
 * The core guarantee: every request that creates, edits, tests or disconnects
 * a connection is the same with the switch on as with it off, for the same
 * input. Each scenario runs once per look through that look's own screen and
 * compares the writes that reached the service. Then the new look's own
 * behaviour: service cards with Connect, connection cards with Reconnect, the
 * test result beside the test, and write-only secrets that are never shown
 * again, logged or kept in browser storage.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { FxProvider } from '@/providers/fx-provider';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { answers, calls, connection, resetCalls, settle, storageConnection, writeCalls } from './integration-test-kit';
import { resetConnectionTestResults } from '../components/connection-test-results';

const h = vi.hoisted(() => ({
  params: { id: 'con-1' } as Record<string, string>,
  search: new URLSearchParams(),
  pathname: '/settings/integrations',
}));

vi.mock('@/lib/toast', async () => (await import('./integration-test-kit')).toastMock);
vi.mock('@/services/integration-service', async () => (await import('./integration-test-kit')).integrationServiceMock);
vi.mock('@/services/pending-actions-service', async () => (await import('./integration-test-kit')).pendingActionsServiceMock);
vi.mock('@/services/preferences-service', async () => (await import('./integration-test-kit')).preferencesServiceMock);

vi.mock('next/navigation', async () => {
  const kit = await import('./integration-test-kit');
  const router = {
    push: (...args: unknown[]) => kit.calls.push(['router.push', ...args]),
    replace: (...args: unknown[]) => kit.calls.push(['router.replace', ...args]),
    prefetch: () => undefined,
    back: () => undefined,
    refresh: () => undefined,
  };
  return {
    useRouter: () => router,
    usePathname: () => h.pathname,
    useSearchParams: () => h.search,
    useParams: () => h.params,
  };
});

vi.mock('next-auth/react', async () => ({
  // The signed-in person, for the done toasts' "by Kay Tan".
  SessionContext: (await import('react')).createContext({ data: { user: { name: 'Kay Tan' } } }),
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
  getSession: () => Promise.resolve(null),
  signOut: () => undefined,
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: () => Promise.resolve({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: () => undefined }),
}));

// Imported after the mocks.
import IntegrationsPage from '../page';
import NewConnectionPage from '../new/page';
import ConnectionFormPage from '../[id]/page';

type Look = 'off' | 'on';

function render(ui: ReactElement, look: Look) {
  const inner = <SettingsProvider>{ui}</SettingsProvider>;
  return rtlRender(
    look === 'on' ? (
      <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
        {inner}
      </FxProvider>
    ) : (
      inner
    ),
  );
}

beforeEach(() => {
  resetCalls();
  resetPageActionsForTests();
  resetConnectionTestResults();
  answers.connection = connection();
  answers.list = [connection(), storageConnection()];
  answers.testOk = true;
  answers.createFails = false;
  h.params = { id: 'con-1' };
  h.search = new URLSearchParams();
  h.pathname = '/settings/integrations';
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.cookie = 'fx_uiux=; Max-Age=0; path=/';
});

afterEach(() => {
  vi.restoreAllMocks();
});

const byName = (root: Element, n: string) => root.querySelector(`input[name="${n}"]`) as HTMLInputElement;

/** Runs a record action: the gear menu with the switch off, the header's
 *  icon action with it on. */
async function runRecordAction(look: Look, name: RegExp): Promise<void> {
  if (look === 'off') {
    const triggers = screen.getAllByRole('button', { name: /actions|more|settings/i });
    fireEvent.pointerDown(triggers[triggers.length - 1], { button: 0 });
    await settle();
    fireEvent.click(await screen.findByRole('menuitem', { name }));
  } else {
    fireEvent.click(screen.getByRole('button', { name }));
  }
  await settle();
}

async function createSmtp(look: Look, secret: string) {
  h.pathname = '/settings/integrations/new';
  h.search = new URLSearchParams('provider=smtp');
  const { container, unmount } = render(<NewConnectionPage />, look);
  await screen.findByPlaceholderText('smtp.example.com');
  await settle();
  fireEvent.change(screen.getByPlaceholderText('smtp.example.com'), { target: { value: 'smtp.maju.my' } });
  fireEvent.change(byName(container, 'config.username'), { target: { value: 'mailer' } });
  fireEvent.change(byName(container, 'credentials.password'), { target: { value: secret } });
  fireEvent.change(byName(container, 'config.fromEmail'), { target: { value: 'hello@maju.my' } });
  fireEvent.click(screen.getByRole('button', { name: /^Create/ }));
  await settle();
  return { container, unmount };
}

/** Edit page: change the name and host, replace the password, save. */
async function editSmtp(look: Look, secret: string | null) {
  h.pathname = '/settings/integrations/con-1';
  h.search = new URLSearchParams('edit=1');
  const { container, unmount } = render(<ConnectionFormPage />, look);
  await screen.findByDisplayValue('smtp.maju.my');
  await settle();
  fireEvent.change(screen.getByDisplayValue('Company mail'), { target: { value: 'Company mail 2' } });
  fireEvent.change(screen.getByDisplayValue('smtp.maju.my'), { target: { value: 'mail.maju.my' } });
  if (secret !== null) {
    if (look === 'on') fireEvent.click(screen.getByRole('button', { name: 'Replace Password' }));
    fireEvent.change(byName(container, 'credentials.password'), { target: { value: secret } });
  }
  fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
  await settle();
  return { container, unmount };
}

async function bothLooks(run: (look: Look) => Promise<{ unmount: () => void }>) {
  const out: Record<Look, unknown[][]> = { off: [], on: [] };
  for (const look of ['off', 'on'] as const) {
    resetCalls();
    resetPageActionsForTests();
    resetConnectionTestResults();
    const { unmount } = await run(look);
    out[look] = writeCalls();
    unmount();
  }
  return out;
}

describe('the same requests in both looks', () => {
  it('creates a connection with the same body', async () => {
    const out = await bothLooks((look) => createSmtp(look, 'pw-123456'));
    expect(out.off.length).toBe(1);
    expect(out.on).toEqual(out.off);
  });

  it('saves an edit that keeps the stored password with the same body', async () => {
    const out = await bothLooks((look) => editSmtp(look, null));
    expect(out.off).toEqual([
      ['integration.update', 'con-1', expect.objectContaining({ name: 'Company mail 2', credentials: {} })],
    ]);
    expect(out.on).toEqual(out.off);
  });

  it('saves an edit that replaces the password with the same body', async () => {
    const out = await bothLooks((look) => editSmtp(look, 'new-pw-9f3a'));
    expect(out.off).toEqual([
      ['integration.update', 'con-1', expect.objectContaining({ credentials: { password: 'new-pw-9f3a' } })],
    ]);
    expect(out.on).toEqual(out.off);
  });

  it('runs Test connection and the targeted test with the same requests', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/integrations/con-1';
      const r = render(<ConnectionFormPage />, look);
      await screen.findByText('smtp.maju.my');
      await settle();
      await runRecordAction(look, /Test connection/);
      fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: ' ops@maju.my ' } });
      fireEvent.click(screen.getByRole('button', { name: /Send test email/ }));
      await settle();
      return r;
    });
    expect(out.off).toEqual([
      ['integration.test', 'con-1'],
      ['integration.test', 'con-1', 'ops@maju.my'],
    ]);
    expect(out.on).toEqual(out.off);
  });

  it('starts Disconnect with the same request', async () => {
    const out = await bothLooks(async (look) => {
      h.pathname = '/settings/integrations/con-1';
      const r = render(<ConnectionFormPage />, look);
      await screen.findByText('smtp.maju.my');
      await settle();
      await runRecordAction(look, /Disconnect/);
      return r;
    });
    expect(out.off).toHaveLength(1);
    expect(out.off[0].slice(0, 4)).toEqual(['pending.park', 'connections.delete', 'connection', 'con-1']);
    expect(out.on).toEqual(out.off);
  });

  it('runs a card Test connection from the list with the same request', async () => {
    const out = await bothLooks(async (look) => {
      const r = render(<IntegrationsPage />, look);
      await screen.findAllByText('Company mail');
      await settle();
      const row =
        look === 'on'
          ? (document.querySelector('[data-fx-connection-card="con-1"]')?.closest('[role="row"], [data-slot="card"], article, li, div[data-row-id]') ??
            document.body)
          : (screen.getAllByText('Company mail')[0].closest('tr') as HTMLElement);
      const trigger = within(row as HTMLElement).getAllByRole('button', { name: /actions|more/i })[0];
      fireEvent.pointerDown(trigger, { button: 0 });
      await settle();
      fireEvent.click(await screen.findByRole('menuitem', { name: /Test connection/ }));
      await settle();
      return r;
    });
    expect(out.off).toEqual([['integration.test', 'con-1']]);
    expect(out.on).toEqual(out.off);
  });
});

describe('the new look', () => {
  it('shows a card per service with its own Connect, opening the form with that provider picked', async () => {
    render(<IntegrationsPage />, 'on');
    const services = await screen.findByRole('region', { name: 'Connect a service' });
    await settle();
    expect(within(services).getByText('SMTP mail server')).toBeInTheDocument();
    const smtpCard = services.querySelector('[data-fx-service="smtp"]') as HTMLElement;
    expect(within(smtpCard).getByText('1 connected')).toBeInTheDocument();
    expect(within(services.querySelector('[data-fx-service="notetaker"]') as HTMLElement).getByText('Not connected')).toBeInTheDocument();
    fireEvent.click(within(services).getByRole('button', { name: 'Connect SMTP mail server' }));
    expect(calls).toContainEqual(['router.push', '/settings/integrations/new?provider=smtp']);
    // No list-level Connect button competes with the cards.
    expect(screen.queryByRole('button', { name: /Connect integration/ })).toBeNull();
  });

  it('shows connections as cards, with Reconnect on the one that needs attention', async () => {
    render(<IntegrationsPage />, 'on');
    await screen.findAllByText('Files bucket');
    await settle();
    const bad = document.querySelector('[data-fx-connection-card="con-2"]') as HTMLElement;
    expect(within(bad).getByText('Needs attention')).toBeInTheDocument();
    expect(within(bad).getByText('The access key was refused.')).toBeInTheDocument();
    const good = document.querySelector('[data-fx-connection-card="con-1"]') as HTMLElement;
    expect(within(good).getByText('Connected')).toBeInTheDocument();
    expect(within(good).queryByRole('button', { name: /Reconnect/ })).toBeNull();
    fireEvent.click(within(bad).getByRole('button', { name: 'Reconnect Files bucket' }));
    expect(calls).toContainEqual(['router.push', '/settings/integrations/con-2?edit=1']);
    expect(writeCalls()).toEqual([]);
  });

  it('shows the test result beside the test instead of a toast', async () => {
    h.pathname = '/settings/integrations/con-1';
    render(<ConnectionFormPage />, 'on');
    await screen.findByText('smtp.maju.my');
    await settle();
    await runRecordAction('on', /Test connection/);
    expect(await screen.findByText(/^Connected and signed in\. Checked/)).toBeInTheDocument();
    answers.testOk = false;
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: 'ops@maju.my' } });
    fireEvent.click(screen.getByRole('button', { name: /Send test email/ }));
    await settle();
    expect(screen.getByRole('alert')).toHaveTextContent('The server refused the password.');
    expect(calls.filter((c) => String(c[0]).startsWith('toast.'))).toEqual([]);
  });

  it('names what was saved and by whom', async () => {
    await editSmtp('on', null);
    expect(calls).toContainEqual(['toast.fxDone', { what: 'Company mail 2 saved', byWhom: 'Kay Tan' }]);
  });

  it('makes Save the red action while editing and Edit at rest', async () => {
    h.pathname = '/settings/integrations/con-1';
    render(<ConnectionFormPage />, 'on');
    await screen.findByText('smtp.maju.my');
    await settle();
    expect(screen.getByRole('button', { name: /^Edit (integration|connection)$/ })).toBeInTheDocument();
  });
});

describe('write-only secrets', () => {
  it('reads "Saved" for a stored password, never a value or a mask', async () => {
    h.pathname = '/settings/integrations/con-1';
    const { container } = render(<ConnectionFormPage />, 'on');
    await screen.findByText('smtp.maju.my');
    await settle();
    expect(container.querySelector('[data-fx-saved-secret="password"]')).toHaveTextContent('Saved');
    expect(container.textContent).not.toContain('••••');
  });

  it('keeps a saved password until Replace, and Keep saved sends nothing', async () => {
    h.pathname = '/settings/integrations/con-1';
    h.search = new URLSearchParams('edit=1');
    const { container } = render(<ConnectionFormPage />, 'on');
    await screen.findByDisplayValue('smtp.maju.my');
    await settle();
    expect(byName(container, 'credentials.password')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Replace Password' }));
    fireEvent.change(byName(container, 'credentials.password'), { target: { value: 'oops-typed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Keep saved' }));
    expect(byName(container, 'credentials.password')).toBeNull();
    fireEvent.change(screen.getByDisplayValue('Company mail'), { target: { value: 'Company mail 3' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
    await settle();
    expect(writeCalls()).toEqual([
      ['integration.update', 'con-1', expect.objectContaining({ credentials: {} })],
    ]);
  });

  it('never shows a new password again, logs it or keeps it in browser storage', async () => {
    const secret = 'S3cret-only-once-7c1d';
    const logs = (['log', 'info', 'warn', 'error', 'debug'] as const).map((k) =>
      vi.spyOn(console, k).mockImplementation(() => undefined),
    );
    const { container } = await editSmtp('on', secret);
    // The save went out with it...
    expect(writeCalls()).toEqual([
      ['integration.update', 'con-1', expect.objectContaining({ credentials: { password: secret } })],
    ]);
    // ...and afterwards it is nowhere on the page.
    await waitFor(() => expect(container.querySelector('[data-fx-saved-secret="password"]')).not.toBeNull());
    expect(container.innerHTML).not.toContain(secret);
    expect(Array.from(container.querySelectorAll('input')).some((i) => i.value === secret)).toBe(false);
    // Opening Edit again starts empty.
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /^Edit (integration|connection)$/ }));
    });
    await settle();
    expect(byName(container, 'credentials.password')).toBeNull();
    expect(container.innerHTML).not.toContain(secret);
    // Not logged, not kept in browser storage or cookies.
    for (const spy of logs) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(secret);
    }
    const stored = [window.localStorage, window.sessionStorage]
      .flatMap((s) => Object.keys(s).map((k) => `${k}=${s.getItem(k)}`))
      .join('\n');
    expect(stored).not.toContain(secret);
    expect(document.cookie).not.toContain(secret);
    // No toast carries it either.
    expect(JSON.stringify(calls.filter((c) => String(c[0]).startsWith('toast.')))).not.toContain(secret);
  });

  it('never keeps a new connection\'s password after Create', async () => {
    const secret = 'Create-pw-41aa';
    const { container } = await createSmtp('on', secret);
    expect(writeCalls()[0]).toEqual(
      ['integration.create', expect.objectContaining({ credentials: { password: secret } })],
    );
    const stored = [window.localStorage, window.sessionStorage]
      .flatMap((s) => Object.keys(s).map((k) => `${k}=${s.getItem(k)}`))
      .join('\n');
    expect(stored).not.toContain(secret);
    expect(JSON.stringify(calls.filter((c) => String(c[0]).startsWith('toast.')))).not.toContain(secret);
    // The form goes to the new record's page (where the password reads Saved).
    expect(calls).toContainEqual(['router.push', '/settings/integrations/con-9']);
    void container;
  });
});
