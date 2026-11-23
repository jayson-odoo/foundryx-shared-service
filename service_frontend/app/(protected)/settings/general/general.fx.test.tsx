/**
 * Settings > General with the Foundryx UIUX switch on (slice W4-SETTINGS):
 * one red action "Save general settings" sends exactly what the switch-off
 * card buttons send for the same input; steppers hold whole numbers inside
 * today's ranges; a view-only user sees plain text; Undo writes the old
 * values back. Switch off is pinned by `__parity__/general.parity.test.tsx`.
 * Requests are captured at `apiFetch`, under the real service.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { fxGeneralBodies } from './fx-general-settings';
import GeneralSettingsPage from './page';

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
const perms = vi.hoisted(() => ({ manage: true }));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (p: string) => (p === 'settings.update' ? perms.manage : true),
    ready: true,
    permissions: new Set<string>(),
  }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/general'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Nurul Huda', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

const STORED = {
  defaultCurrency: 'MYR',
  priceDecimals: 2,
  deferredDestructiveSeconds: 10,
  deferredReversibleSeconds: 5,
};

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
      body: JSON.parse(String((init as RequestInit).body)),
    }));
}

beforeEach(() => {
  perms.manage = true;
  net.apiFetch.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  net.apiFetch.mockImplementation(async (_path: string, init?: RequestInit) =>
    init?.body ? { ...STORED, ...JSON.parse(String(init.body)) } : STORED,
  );
});
afterEach(() => resetPageActionsForTests());

/** Types a value into a stepper (or a number field) and leaves it. */
/**
 * Type a value and leave the field. The change is sent twice on purpose: the
 * render that first shows a field (the settings load resolving) is not a user
 * event, so React runs its effects on a later scheduler task, and on a loaded
 * runner the test can type before that task runs. The first change's render
 * then runs the stepper's mount-time text sync AFTER the typed text, putting
 * the loaded value back. The second change types for real; it is a no-op when
 * the first one already stuck.
 */
function typeInto(el: HTMLElement, value: string) {
  fireEvent.change(el, { target: { value } });
  fireEvent.change(el, { target: { value } });
  fireEvent.blur(el);
}

type Edit = { decimals?: string; deletes?: string; others?: string };

async function saveOff(edit: Edit) {
  const view = render(<GeneralSettingsPage />, { wrapper: look(false) });
  await screen.findByDisplayValue('10');
  // The currency and Undo-window cards load separately; '10' only proves the
  // second one. Wait for both Save buttons, which stay disabled while their
  // card loads, so a click on the currency card's is never a no-op.
  await waitFor(() =>
    screen
      .getAllByRole('button', { name: 'Save settings' })
      .forEach((button) => expect(button).toBeEnabled()),
  );
  if (edit.decimals) typeInto(screen.getByLabelText('Price decimal places'), edit.decimals);
  if (edit.deletes) typeInto(screen.getByDisplayValue('10'), edit.deletes);
  if (edit.others) typeInto(screen.getByDisplayValue('5'), edit.others);
  const [currencyBtn, windowsBtn] = screen.getAllByRole('button', { name: 'Save settings' });
  const currency = Boolean(edit.decimals);
  const windows = Boolean(edit.deletes || edit.others);
  if (currency || !windows) {
    fireEvent.click(currencyBtn);
    await waitFor(() => expect(writes()).toHaveLength(1));
  }
  if (windows || !currency) {
    const before = writes().length;
    fireEvent.click(windowsBtn);
    await waitFor(() => expect(writes()).toHaveLength(before + 1));
  }
  return view;
}

async function saveOn(edit: Edit) {
  const view = render(<GeneralSettingsPage />, { wrapper: look(true) });
  await screen.findByLabelText('After a delete');
  if (edit.decimals) typeInto(screen.getByLabelText('Price decimal places'), edit.decimals);
  if (edit.deletes) typeInto(screen.getByLabelText('After a delete'), edit.deletes);
  if (edit.others) typeInto(screen.getByLabelText('After other actions'), edit.others);
  // The page registers its header Save from an effect after the load, so with
  // nothing typed it can still be on its way: find it rather than get it.
  fireEvent.click(await screen.findByRole('button', { name: 'Save general settings' }));
  await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
  return view;
}

describe('the same saves in both looks', () => {
  it.each<[string, Edit]>([
    ['the decimals only', { decimals: '3' }],
    ['the delete window only', { deletes: '15' }],
    ['both Undo windows', { deletes: '20', others: '8' }],
    ['the decimals and a window', { decimals: '0', others: '3' }],
    ['nothing (both cards, as pressing both buttons)', {}],
  ])('%s', async (_name, edit) => {
    (await saveOff(edit)).unmount();
    const off = writes();
    net.apiFetch.mockClear();
    resetPageActionsForTests();
    await saveOn(edit);
    await waitFor(() => expect(writes()).toHaveLength(off.length));
    expect(writes()).toEqual(off);
    for (const w of off) {
      expect(w.path).toBe('/settings/general');
      expect(w.method).toBe('PUT');
    }
  });

  it('the body builder sends the currency card body for a currency change', () => {
    const base = { ...STORED };
    expect(fxGeneralBodies(base, { ...base, defaultCurrency: 'USD' })).toEqual([
      { defaultCurrency: 'USD', priceDecimals: 2 },
    ]);
    expect(fxGeneralBodies(base, { ...base, deferredReversibleSeconds: 9 })).toEqual([
      { deferredDestructiveSeconds: 10, deferredReversibleSeconds: 9 },
    ]);
  });
});

describe('steppers', () => {
  it('hold whole numbers inside the switch-off ranges, with no float noise', async () => {
    await saveOn({ decimals: '2.7', deletes: '99', others: '0' });
    const [currency, windows] = writes();
    expect(currency.body).toEqual({ defaultCurrency: 'MYR', priceDecimals: 3 });
    expect(windows.body).toEqual({ deferredDestructiveSeconds: 60, deferredReversibleSeconds: 1 });
    expect(Number.isInteger(currency.body.priceDecimals)).toBe(true);
  });

  it('+ steps the decimals by exactly one', async () => {
    render(<GeneralSettingsPage />, { wrapper: look(true) });
    await screen.findByLabelText('Price decimal places');
    const plus = screen.getAllByRole('button', { name: 'Increase' })[0];
    fireEvent.pointerDown(plus);
    fireEvent.pointerUp(plus);
    fireEvent.click(screen.getByRole('button', { name: 'Save general settings' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ defaultCurrency: 'MYR', priceDecimals: 3 });
  });
});

describe('done toast and Undo', () => {
  it('says what was saved and by whom; Undo writes the earlier values back', async () => {
    await saveOn({ deletes: '15' });
    const done = toasts.fxDone.mock.calls[0][0];
    expect(done.what).toBe('General settings saved');
    expect(done.byWhom).toBe('Nurul Huda');
    net.apiFetch.mockClear();
    done.undo();
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ deferredDestructiveSeconds: 10, deferredReversibleSeconds: 5 });
  });
});

describe('view-only', () => {
  it('shows plain text and no red action', async () => {
    perms.manage = false;
    render(<GeneralSettingsPage />, { wrapper: look(true) });
    expect(await screen.findByText('10 s')).toBeInTheDocument();
    expect(screen.getByText('MYR')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save general settings' })).toBeNull();
    expect(screen.queryByRole('spinbutton')).toBeNull();
  });
});
