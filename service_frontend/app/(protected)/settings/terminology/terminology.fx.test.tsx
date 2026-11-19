/**
 * Settings > Terminology and Settings > Numbering with the Foundryx UIUX
 * switch on (slice W4-SETTINGS): a rename, a numbering edit and a reset send
 * exactly what they send with the switch off for the same input; the done
 * toasts' Undo puts back exactly what was there (terminology) or is not
 * offered (numbering). Switch off is pinned by the pages' `__parity__`
 * tests. Requests are captured at `apiFetch`, under the real services.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { TERMS_FIXTURE } from './terminology-fixture.test-data';
import { NUMBERS_FIXTURE } from '../numbering/numbering-fixture.test-data';
import TerminologyPage from './page';
import NumberingPage from '../numbering/page';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
const toasts = vi.hoisted(() => ({ fxDone: vi.fn(), error: vi.fn(), success: vi.fn() }));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@/hooks/use-view-preferences', () => ({
  useViewPreferences: () => ({
    isLoaded: true,
    columnOrder: [],
    columnVisibility: {},
    columnSizing: {},
    setColumnOrder: () => {},
    setColumnVisibility: () => {},
    setColumnSizing: () => {},
  }),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/terminology'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Nurul Huda', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <SettingsProvider>
        <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
          {children}
        </FxProvider>
      </SettingsProvider>
    );
  };
}

function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method)
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  net.apiFetch.mockImplementation(async (path: string) => {
    if (path === '/terminology/catalog') return TERMS_FIXTURE;
    if (path === '/numbering') return NUMBERS_FIXTURE;
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

/** Opens a row's action menu and picks an item. */
async function rowAction(rowText: string, item: RegExp) {
  // The new look also renders hidden measuring copies of a cell: take the
  // first copy that sits in a row.
  const cells = await screen.findAllByText(rowText);
  const row = cells
    .map((c) => c.closest('tr, [role="row"], [data-fx-card]'))
    .find(Boolean) as HTMLElement;
  const trigger = within(row).getAllByRole('button', { name: 'Actions' })[0];
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole('menuitem', { name: item }));
}

async function rename(on: boolean, key: string, singular: string, plural: string) {
  const view = render(<TerminologyPage />, { wrapper: look(on) });
  await rowAction(key, /Edit/);
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText(/Singular/), { target: { value: singular } });
  fireEvent.change(within(dialog).getByLabelText(/Plural/), { target: { value: plural } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save label' }));
  await waitFor(() => expect(writes()).toHaveLength(1));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  return view;
}

describe('Terminology: the same rename in both looks', () => {
  it.each([
    ['contact', ' Customer ', 'Customers'],
    ['product', 'Article', ' Articles '],
  ])('%s', async (key, singular, plural) => {
    (await rename(false, key, singular, plural)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    resetPageActionsForTests();
    await rename(true, key, singular, plural);
    expect(writes()).toEqual(off);
  });

  it('Undo of a first rename resets the term; of a second rename puts the earlier names back', async () => {
    (await rename(true, 'contact', 'Customer', 'Customers')).unmount();
    expect(toasts.fxDone.mock.calls[0][0]).toMatchObject({
      what: 'Contact renamed to Customer',
      byWhom: 'Nurul Huda',
    });
    net.apiFetch.mockClear();
    toasts.fxDone.mock.calls[0][0].undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ path: '/terminology/contact', method: 'DELETE', body: null });

    net.apiFetch.mockClear();
    toasts.fxDone.mockClear();
    await rename(true, 'product', 'Article', 'Articles');
    net.apiFetch.mockClear();
    toasts.fxDone.mock.calls[0][0].undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      path: '/terminology/product',
      method: 'PUT',
      body: JSON.stringify({ singular: 'Item', plural: 'Items' }),
    });
  });

  it('the list is reloaded in place, not rebuilt', async () => {
    await rename(true, 'contact', 'Customer', 'Customers');
    const catalogReads = () =>
      net.apiFetch.mock.calls.filter(([p]) => p === '/terminology/catalog').length;
    await waitFor(() => expect(catalogReads()).toBe(2));
  });

  it('Reset to default sends the same DELETE and offers Undo back to the override', async () => {
    render(<TerminologyPage />, { wrapper: look(true) });
    await rowAction('product', /Reset to default/);
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    expect(writes()).toEqual([{ path: '/terminology/product', method: 'DELETE', body: null }]);
    expect(toasts.fxDone.mock.calls[0][0].what).toBe('Item reset to Product');
    net.apiFetch.mockClear();
    toasts.fxDone.mock.calls[0][0].undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toBe(JSON.stringify({ singular: 'Item', plural: 'Items' }));
  });
});

type NumEdit = { prefix?: string; next?: string; format?: string };

async function editNumbering(on: boolean, docType: string, edit: NumEdit, expectWrites: number) {
  const view = render(<NumberingPage />, { wrapper: look(on) });
  await rowAction(docType, /Edit/);
  const dialog = await screen.findByRole('dialog');
  if (edit.prefix !== undefined)
    fireEvent.change(within(dialog).getByLabelText('Prefix'), { target: { value: edit.prefix } });
  if (edit.format !== undefined)
    fireEvent.change(within(dialog).getByLabelText(/Format pattern/), { target: { value: edit.format } });
  if (edit.next !== undefined) {
    const next = within(dialog).getByLabelText(/Next value/);
    fireEvent.change(next, { target: { value: edit.next } });
    fireEvent.blur(next);
  }
  fireEvent.click(within(dialog).getByRole('button', { name: /^Save .*numbering$/ }));
  await waitFor(() => expect(writes()).toHaveLength(expectWrites));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  return view;
}

describe('Numbering: the same edit in both looks', () => {
  it.each<[string, string, NumEdit, number]>([
    ['a new prefix and next number', 'invoice', { prefix: ' IV/ ', next: '100' }, 2],
    ['a new format only', 'quotation', { format: ' {prefix}{YY}-{NNNN} ' }, 1],
    ['a typed decimal next number (cut to its whole part in both)', 'invoice', { next: '100.7' }, 2],
    ['nothing changed', 'quotation', {}, 1],
  ])('%s', async (_name, docType, edit, count) => {
    (await editNumbering(false, docType, edit, count)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    resetPageActionsForTests();
    await editNumbering(true, docType, edit, count);
    expect(writes()).toEqual(off);
  });

  it('a decimal next number is sent as a whole number', async () => {
    await editNumbering(true, 'invoice', { next: '100.7' }, 2);
    expect(writes()[1]).toEqual({
      path: '/numbering/invoice/next-val',
      method: 'PUT',
      body: JSON.stringify({ nextVal: 100 }),
    });
    expect(toasts.fxDone.mock.calls[0][0]).toMatchObject({
      what: 'Numbering saved for Invoice',
      howMany: 'next number 100',
    });
    expect(toasts.fxDone.mock.calls[0][0].undo).toBeUndefined();
  });

  it('Reset to default sends the same DELETE, with no Undo', async () => {
    render(<NumberingPage />, { wrapper: look(true) });
    await rowAction('quotation', /Reset to default/);
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    expect(writes()).toEqual([{ path: '/numbering/quotation', method: 'DELETE', body: null }]);
    expect(toasts.fxDone.mock.calls[0][0].undo).toBeUndefined();
  });
});
