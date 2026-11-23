/**
 * W4-AI, Claude connector, with the Foundryx UIUX switch on.
 *
 * Core guarantee: every request these pages send is the same in both looks
 * for the same input. Each case drives the real page (real hooks, services,
 * `ResourceForm`) through the controls each look shows and compares what
 * reaches `lib/api-client`: product create and edit (fields, a replaced
 * secret, a kept secret, a removed secret), delete of saved settings, access
 * settings, manifest refresh, grant revoke (record page, row and bulk).
 *
 * Secrets: a typed secret is sent once and then never shown, kept in browser
 * storage, logged or put in a toast. Permissions: neither look shows more
 * to a user than today.
 */
import { act, cleanup, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { FX_SETTINGS_STORAGE_KEY } from '@/lib/fx/settings-schema';
import { toast } from '@/lib/toast';
import ClaudeConnectorPage from '../page';
import { GrantDetailView } from '../components/grant-detail-view';
import { ProductFormView } from '../components/product-form-view';
import { useConnectorGrantActions } from '../components/use-connector-grant-list-config';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { ALL_PERMISSIONS, GRANT, GRANTS, Look, writes, type RecordedWrite } from './cc-kit';

const nav = vi.hoisted(() => ({ path: '/settings/claude-connector' }));
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
  const kit = await import('./cc-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
  };
});

beforeEach(() => {
  perms.splice(0, perms.length, ...ALL_PERMISSIONS);
  // Single click instead of press and hold, so a plain confirm can be driven.
  localStorage.setItem(FX_SETTINGS_STORAGE_KEY, JSON.stringify({ hold: false }));
});

afterEach(() => {
  cleanup();
  writes.length = 0;
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

async function mount(fx: boolean, path: string, ui: React.ReactElement, ready: string) {
  nav.path = path;
  let unmount!: () => void;
  await act(async () => {
    unmount = render(<Look fx={fx}>{ui}</Look>).unmount;
  });
  await waitFor(() => expect(document.body.textContent).toContain(ready));
  await settle();
  return unmount;
}

/** Renders `ui` in one look, runs `steps`, returns the writes it sent. */
async function sent(
  fx: boolean,
  path: string,
  ui: React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<RecordedWrite[]> {
  writes.length = 0;
  const u = userEvent.setup();
  const unmount = await mount(fx, path, ui, ready);
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

const redAction = () => document.querySelector<HTMLElement>('[data-fx-main-action] button');

/** Save / Create: the record card's button while off, the red action while on. */
async function save(u: Ui, fx: boolean, offLabel: string) {
  if (fx) {
    expect(redAction()).not.toBeNull();
    await u.click(redAction()!);
  } else {
    await u.click(screen.getByRole('button', { name: offLabel }));
  }
  await settle();
}

async function typeLabelled(u: Ui, label: string, text: string) {
  const input = screen.getByLabelText(label, { selector: 'input' });
  await u.clear(input);
  await u.type(input, text);
}

/** A secret field: typed straight in while off; Replace first while on (when one is saved). */
async function typeSecret(u: Ui, fx: boolean, label: string, text: string, saved: boolean) {
  if (fx && saved) {
    await u.click(screen.getAllByRole('button', { name: 'Replace' })[0]);
  }
  await typeLabelled(u, label, text);
}

/** Opens the record's other actions: the gear while off, More (or icon) while on. */
async function formMenuItem(u: Ui, fx: boolean, item: string) {
  if (fx) {
    await u.click(screen.getByRole('button', { name: 'More' }));
  } else {
    await u.click(screen.getByRole('button', { name: 'Actions' }));
  }
  await u.click(await screen.findByRole('menuitem', { name: item }));
}

const NEW_PRODUCT = () => <ProductFormView initialEditing />;
const EDIT_PRODUCT = () => <ProductFormView productKey="sorento" initialEditing />;
const READ_PRODUCT = () => <ProductFormView productKey="sorento" initialEditing={false} />;

describe('Claude connector: the same requests in both looks', () => {
  it('creates a product with both secrets', async () => {
    const out = await bothLooks('/settings/claude-connector/products/new', NEW_PRODUCT, 'New product', async (u, fx) => {
      await typeLabelled(u, 'Key', 'ledger');
      await typeLabelled(u, 'Display name', 'Ledger');
      await typeLabelled(u, 'Connection ID', 'conn-ledger');
      await typeLabelled(u, 'Consent URL', 'https://ledger.test/connect');
      await typeLabelled(u, 'API base URL', 'https://ledger.test/api');
      await u.click(screen.getByRole('tab', { name: 'Secrets' }));
      await typeSecret(u, fx, 'Secret to product', 'to-product-secret-0001', false);
      await typeSecret(u, fx, 'Secret from product', 'from-product-secret-0002', false);
      await save(u, fx, 'Create product');
    });
    expect(out).toEqual([
      {
        method: 'POST',
        path: '/connector/products',
        body: expect.objectContaining({
          key: 'ledger',
          displayName: 'Ledger',
          ssToProductSecret: 'to-product-secret-0001',
          productToSsSecret: 'from-product-secret-0002',
        }),
      },
    ]);
  });

  it('edits fields and replaces a saved secret', async () => {
    const out = await bothLooks('/settings/claude-connector/products/sorento', EDIT_PRODUCT, 'Sorento CRM', async (u, fx) => {
      await typeLabelled(u, 'Display name', 'Sorento');
      await u.click(screen.getByRole('tab', { name: 'Advanced' }));
      await typeLabelled(u, 'Issuer', 'sorento-2');
      await u.click(screen.getByRole('tab', { name: 'Secrets' }));
      await typeSecret(u, fx, 'Secret to product', 'replaced-secret-0003', true);
      await save(u, fx, 'Save product');
    });
    expect(out[0]).toMatchObject({
      method: 'PUT',
      path: '/connector/products/sorento/settings',
      body: { displayName: 'Sorento', issuer: 'sorento-2', ssToProductSecret: 'replaced-secret-0003' },
    });
  });

  it('keeps a saved secret when it is left alone (and when Replace is opened and left blank)', async () => {
    const out = await bothLooks('/settings/claude-connector/products/sorento', EDIT_PRODUCT, 'Sorento CRM', async (u, fx) => {
      await typeLabelled(u, 'Display name', 'Sorento');
      await u.click(screen.getByRole('tab', { name: 'Secrets' }));
      if (fx) await u.click(screen.getAllByRole('button', { name: 'Replace' })[0]);
      await save(u, fx, 'Save product');
    });
    expect(out[0].body).not.toHaveProperty('ssToProductSecret');
    expect(out[0].body).not.toHaveProperty('productToSsSecret');
  });

  it('removes a saved secret', async () => {
    const out = await bothLooks('/settings/claude-connector/products/sorento', EDIT_PRODUCT, 'Sorento CRM', async (u, fx) => {
      await u.click(screen.getByRole('tab', { name: 'Secrets' }));
      await u.click(screen.getByRole('checkbox'));
      await save(u, fx, 'Save product');
    });
    expect(out[0].body).toMatchObject({ clearSecrets: ['ssToProduct'] });
  });

  it('deletes the saved settings after the key is typed', async () => {
    const out = await bothLooks('/settings/claude-connector/products/sorento', READ_PRODUCT, 'conn-sorento', async (u, fx) => {
      await formMenuItem(u, fx, 'Delete saved settings');
      const dialog = await screen.findByRole('alertdialog');
      const input = within(dialog).getByRole('textbox');
      await u.type(input, 'sorento');
      await u.click(within(dialog).getByRole('button', { name: 'Delete' }));
    });
    expect(out).toEqual([
      { method: 'DELETE', path: '/connector/products/sorento', body: { confirmKey: 'sorento' } },
    ]);
  });

  it('saves the access settings', async () => {
    await bothLooks('/settings/claude-connector', () => <ClaudeConnectorPage />, 'Recent changes', async (u) => {
      await u.click(screen.getByRole('tab', { name: 'Access' }));
      await u.click(screen.getByRole('button', { name: 'Edit' }));
      await typeLabelled(u, 'Public base URL', 'https://ss2.example.test');
      await u.click(screen.getByRole('button', { name: 'Save settings' }));
    });
  });

  it('refreshes a manifest', async () => {
    const out = await bothLooks('/settings/claude-connector', () => <ClaudeConnectorPage />, 'Lim Wei Jie', async (u) => {
      await u.click(screen.getByRole('tab', { name: 'Products' }));
      await waitFor(() => expect(screen.getAllByRole('button', { name: 'Refresh manifest' }).length).toBe(2));
      await u.click(screen.getAllByRole('button', { name: 'Refresh manifest' })[0]);
    });
    expect(out).toEqual([{ method: 'POST', path: '/connector/products/sorento/refresh-manifest', body: null }]);
  });

  it('revokes a grant from its record page', async () => {
    const out = await bothLooks('/settings/claude-connector/g-1', () => <GrantDetailView grantId="g-1" />, 'crm-user-42', async (u, fx) => {
      if (fx) {
        await u.click(redAction()!);
      } else {
        await u.click(screen.getByRole('button', { name: 'Actions' }));
        await u.click(await screen.findByRole('menuitem', { name: 'Revoke' }));
      }
      const dialog = await screen.findByRole('alertdialog');
      await u.click(within(dialog).getByRole('button', { name: 'Revoke' }));
    });
    expect(out).toEqual([{ method: 'POST', path: '/connector/grants/g-1/revoke', body: null }]);
  });

  it('row and bulk revoke run the same requests', async () => {
    async function run(fx: boolean, id: 'revoke' | 'revoke-bulk', rows = GRANTS) {
      writes.length = 0;
      vi.spyOn(toast, 'fxDone').mockReturnValue(0);
      vi.spyOn(toast, 'success').mockReturnValue(0);
      const { result, unmount } = renderHook(() => useConnectorGrantActions(), {
        wrapper: ({ children }) => <Look fx={fx}>{children}</Look>,
      });
      const action = result.current.find((a) => a.id === id)!;
      await act(async () => {
        await action.run!(rows, { reload: () => {} });
      });
      unmount();
      return writes.map((w) => ({ ...w }));
    }
    expect(await run(true, 'revoke', [GRANT])).toEqual(await run(false, 'revoke', [GRANT]));
    const bulkOff = await run(false, 'revoke-bulk');
    expect(bulkOff).toEqual([
      { method: 'POST', path: '/connector/grants/bulk-revoke', body: { ids: ['g-1', 'g-2'] } },
    ]);
    expect(await run(true, 'revoke-bulk')).toEqual(bulkOff);
  });
});

describe('Claude connector: secrets are write-only', () => {
  const SECRET = 'typed-secret-ZQ81-x7p4';

  it.each([false, true])('a typed secret is sent, then never shown, stored, logged or toasted (switch %s)', async (fx) => {
    const logs = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => {}),
    );
    const toasts = [
      vi.spyOn(toast, 'fxDone').mockReturnValue(0),
      vi.spyOn(toast, 'success').mockReturnValue(0),
      vi.spyOn(toast, 'error').mockReturnValue(0),
    ];
    const u = userEvent.setup();
    const unmount = await mount(fx, '/settings/claude-connector/products/sorento', EDIT_PRODUCT(), 'Sorento CRM');
    await u.click(screen.getByRole('tab', { name: 'Secrets' }));
    await typeSecret(u, fx, 'Secret to product', SECRET, true);
    await save(u, fx, 'Save product');
    expect(writes.at(-1)?.body).toMatchObject({ ssToProductSecret: SECRET });

    // Gone from the page once saved (the form is back to read, blank fields).
    expect(document.body.innerHTML).not.toContain(SECRET);
    for (const input of Array.from(document.querySelectorAll('input'))) expect(input.value).not.toContain(SECRET);
    const stored = [localStorage, sessionStorage].flatMap((s) =>
      Object.keys(s).map((k) => `${k}=${s.getItem(k)}`),
    );
    expect(stored.join('\n')).not.toContain(SECRET);
    expect(document.cookie).not.toContain(SECRET);
    for (const spy of [...logs, ...toasts]) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    unmount();
  });

  it('a saved secret comes back as its ending with Replace, never filled in (switch on)', async () => {
    const u = userEvent.setup();
    await mount(true, '/settings/claude-connector/products/sorento', EDIT_PRODUCT(), 'Sorento CRM');
    await u.click(screen.getByRole('tab', { name: 'Secrets' }));
    expect(screen.getByText('ending a91c')).toBeTruthy();
    expect(screen.queryByText(/\*\*\*\*/)).toBeNull();
    expect(screen.queryByLabelText('Secret to product', { selector: 'input' })).toBeNull();
    await u.click(screen.getAllByRole('button', { name: 'Replace' })[0]);
    const input = screen.getByLabelText('Secret to product', { selector: 'input' }) as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(input.value).toBe('');
  });
});

describe('Claude connector: who sees what is the same in both looks', () => {
  it.each([false, true])('without connector.read every page shows no access (switch %s)', async (fx) => {
    perms.splice(0, perms.length, 'connector.settings', 'connector.manage');
    const Page = (await import('../page')).default;
    const GrantPage = (await import('../[id]/page')).default;
    const ProductPage = (await import('../products/[key]/page')).default;
    for (const ui of [<Page key="a" />, <GrantPage key="b" />, <ProductPage key="c" />]) {
      const unmount = await mount(fx, '/settings/claude-connector', ui, 'have access');
      expect(redAction()).toBeNull();
      expect(writes).toEqual([]);
      unmount();
      document.body.innerHTML = '';
    }
  });

  it.each([false, true])('a read-only user gets no add, edit or revoke (switch %s)', async (fx) => {
    perms.splice(0, perms.length, 'connector.read');
    let unmount = await mount(fx, '/settings/claude-connector', <ClaudeConnectorPage />, 'Lim Wei Jie');
    const u = userEvent.setup();
    await u.click(screen.getByRole('tab', { name: 'Products' }));
    await waitFor(() => expect(document.body.textContent).toContain('MCP URL'));
    expect(screen.queryByRole('link', { name: /Add product/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Add product/ })).toBeNull();
    expect(redAction()).toBeNull();
    expect(screen.queryByRole('button', { name: 'Refresh manifest' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    unmount();
    resetPageActionsForTests();
    document.body.innerHTML = '';

    unmount = await mount(fx, '/settings/claude-connector/g-1', <GrantDetailView grantId="g-1" />, 'crm-user-42');
    expect(redAction()).toBeNull();
    expect(screen.queryByRole('button', { name: /Revoke/ })).toBeNull();
    unmount();
    resetPageActionsForTests();
    document.body.innerHTML = '';

    unmount = await mount(fx, '/settings/claude-connector/products/sorento', READ_PRODUCT(), 'conn-sorento');
    expect(redAction()).toBeNull();
    expect(screen.queryByRole('button', { name: /^Edit/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull();
    unmount();
  });
});

describe('Claude connector under the new look', () => {
  it('Add product is the red action on the Products tab only', async () => {
    const u = userEvent.setup();
    await mount(true, '/settings/claude-connector', <ClaudeConnectorPage />, 'Lim Wei Jie');
    expect(redAction()).toBeNull();
    await u.click(screen.getByRole('tab', { name: 'Products' }));
    await waitFor(() => expect(redAction()?.textContent).toContain('Add product'));
    expect(screen.queryByRole('link', { name: /Add product/ })).toBeNull();
    // Products are connected-service cards with a state chip and saved / not set secrets.
    const card = document.querySelector('[data-fx-product-card="sorento"]') as HTMLElement;
    expect(within(card).getByText('Ready')).toBeTruthy();
    expect(within(card).getByText('Saved')).toBeTruthy();
    expect(within(card).getByText('Not set')).toBeTruthy();
    const stale = document.querySelector('[data-fx-product-card="ledger"]') as HTMLElement;
    expect(within(stale).getByText('Needs attention')).toBeTruthy();
    await u.click(screen.getByRole('tab', { name: 'Grants' }));
    await waitFor(() => expect(redAction()).toBeNull());
  });

  it('the grant page names who loses access to what', async () => {
    await mount(true, '/settings/claude-connector/g-1', <GrantDetailView grantId="g-1" />, 'crm-user-42');
    const red = redAction()!;
    expect(red.getAttribute('aria-label') ?? red.textContent).toMatch(/Revoke Jane Doe's access to Sorento CRM|Revoke/);
    expect(document.body.innerHTML).toContain("Revoke Jane Doe's access to Sorento CRM");
  });

  it('bulk revoke asks for the number of grants, keeps today\'s REVOKE while off', async () => {
    const { result } = renderHook(() => useConnectorGrantActions(), {
      wrapper: ({ children }) => <Look fx>{children}</Look>,
    });
    const bulk = result.current.find((a) => a.id === 'revoke-bulk')!;
    const onConfirm = vi.fn();
    render(
      <Look fx>
        <ConfirmActionDialog pending={bulk} rows={GRANTS} onClose={() => {}} onConfirm={onConfirm} />
      </Look>,
    );
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByLabelText('Type "2"')).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: 'Keep access' })).toBeTruthy();
    cleanup();

    const off = renderHook(() => useConnectorGrantActions(), {
      wrapper: ({ children }) => <Look fx={false}>{children}</Look>,
    });
    const bulkOff = off.result.current.find((a) => a.id === 'revoke-bulk')!;
    render(
      <Look fx={false}>
        <ConfirmActionDialog pending={bulkOff} rows={GRANTS} onClose={() => {}} onConfirm={onConfirm} />
      </Look>,
    );
    expect((await screen.findByLabelText('Confirmation text')).getAttribute('placeholder')).toBe('REVOKE');
  });
});
