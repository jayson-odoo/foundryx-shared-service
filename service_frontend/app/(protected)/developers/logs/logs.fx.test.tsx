/**
 * The developer logs pages with the Foundryx UIUX switch on (slice W3-LOGS).
 *
 * - Log retention: the same save request in both looks for the same days
 *   (captured at `apiFetch`, under the real service: same path, method and
 *   body); a value that is not a whole number of days sends nothing; the
 *   done toast's Undo is offered only when the old window was a custom one.
 * - The list and one log are read-only: moments in the 12-hour form, Hold to
 *   Copy on identifiers and the time only, never on the error text or the
 *   payloads, which stay as they are.
 *
 * Switch off is pinned by `__parity__/logs.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { IntegrationLogDetail } from '@/types/integration-logs';
import DeveloperLogSettingsPage from './settings/page';
import { fxRetentionDays } from './components/fx-log-retention-form';
import { LogDetailView } from './components/log-detail-view';
import { useIntegrationLogsListConfig } from './components/use-integration-logs-list-config';

const net = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchText: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch, apiFetchText: net.apiFetchText };
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
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/developers/logs/settings'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

/** Every write sent: path, method and body. */
function writes() {
  return [...net.apiFetch.mock.calls, ...net.apiFetchText.mock.calls]
    .filter(([, init]) => init && (init as RequestInit).method && (init as RequestInit).method !== 'GET')
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

const LOG: IntegrationLogDetail = {
  id: 'log-2',
  tenantId: 'ten-1',
  traceId: 'trc-7f3a',
  source: 'outbound_meta',
  workspaceId: null,
  apiKeyId: 'key-42',
  operation: 'POST /messages',
  method: 'POST',
  status: 'error',
  statusCode: 400,
  errorCode: 'template_paused',
  latencyMs: 61,
  externalRef: 'wamid.HBgM',
  createdAt: '2026-11-05T07:04:00Z',
  errorMessage: 'Bearer sk_live_SECRETVALUE rejected',
  requestSummary: { to: '60•••••789', template: 'promo_nov' },
  responseSummary: { error: { code: 132015 } },
};

let stored = { retentionDays: 30, isDefault: true };

beforeEach(() => {
  stored = { retentionDays: 30, isDefault: true };
  net.apiFetch.mockReset();
  net.apiFetchText.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/integration-logs/settings' && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body)) as { retentionDays: number };
      stored = { retentionDays: body.retentionDays, isDefault: false };
      return stored;
    }
    if (path === '/integration-logs/settings') return stored;
    if (path.startsWith('/integration-logs/trace/')) return { traceId: 'trc-7f3a', legs: [LOG] };
    if (path === '/integration-logs/log-2') return LOG;
    if (path.startsWith('/integration-logs')) return { data: [LOG], total: 1, page: 0 };
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

async function saveOff(days: string) {
  const view = render(<DeveloperLogSettingsPage />, { wrapper: look(false) });
  const input = await screen.findByDisplayValue(String(stored.retentionDays));
  fireEvent.change(input, { target: { value: days } });
  fireEvent.click(screen.getByRole('button', { name: 'Save log settings' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save log settings' })).not.toBeDisabled());
  view.unmount();
}

async function saveOn(days: string) {
  const view = render(<DeveloperLogSettingsPage />, { wrapper: look(true) });
  const input = await screen.findByRole('spinbutton');
  await waitFor(() => expect(input).not.toBeDisabled());
  fireEvent.change(input, { target: { value: days } });
  fireEvent.blur(input);
  const main = document.querySelector('[data-fx-main-action] button') as HTMLElement;
  expect(main).not.toBeNull();
  await act(async () => {
    fireEvent.click(main);
  });
  await waitFor(() => expect(main).not.toHaveAttribute('aria-busy', 'true'));
  return view;
}

describe('log retention: the same save in both looks', () => {
  it('sends the same PUT for the same number of days', async () => {
    await saveOff('45');
    const off = writes();
    expect(off).toEqual([
      { path: '/integration-logs/settings', method: 'PUT', body: JSON.stringify({ retentionDays: 45 }) },
    ]);
    expect(toasts.success).toHaveBeenCalledWith('Log retention saved.');

    net.apiFetch.mockClear();
    stored = { retentionDays: 30, isDefault: true };
    const view = await saveOn('45');
    await waitFor(() => expect(writes()).toEqual(off));
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Developer logs kept for 45 days',
      byWhom: 'Nurul Huda',
      undo: undefined,
    });
    // The red action is the one Save on the page: no second button below.
    expect(screen.queryByRole('button', { name: 'Save log settings' })).toBeNull();
    view.unmount();
  });

  it('a typed value past the range is kept inside it, and that is what is sent', async () => {
    await saveOn('9999');
    await waitFor(() =>
      expect(writes()).toEqual([
        { path: '/integration-logs/settings', method: 'PUT', body: JSON.stringify({ retentionDays: 3650 }) },
      ]),
    );
  });

  it('a value that is not a whole number of days sends nothing and says why', async () => {
    await saveOn('6.5');
    expect(await screen.findByText('Enter a whole number of days between 1 and 3650.')).toBeInTheDocument();
    expect(writes()).toEqual([]);
    expect(toasts.fxDone).not.toHaveBeenCalled();
  });

  it('Undo writes the old custom window back; there is no Undo for the deployment default', async () => {
    stored = { retentionDays: 14, isDefault: false };
    await saveOn('45');
    await waitFor(() => expect(toasts.fxDone).toHaveBeenCalled());
    const { undo } = toasts.fxDone.mock.calls[0][0] as { undo?: () => void };
    expect(undo).toBeTypeOf('function');
    net.apiFetch.mockClear();
    await act(async () => {
      undo!();
    });
    await waitFor(() =>
      expect(writes()).toEqual([
        { path: '/integration-logs/settings', method: 'PUT', body: JSON.stringify({ retentionDays: 14 }) },
      ]),
    );
  });

  it('the rule for a valid window is the same as with the switch off', () => {
    expect(fxRetentionDays(1)).toBe(1);
    expect(fxRetentionDays(3650)).toBe(3650);
    expect(fxRetentionDays(0)).toBeNull();
    expect(fxRetentionDays(3651)).toBeNull();
    expect(fxRetentionDays(6.5)).toBeNull();
    expect(fxRetentionDays(null)).toBeNull();
  });
});

describe('the logs list under the switch', () => {
  it('copies identifiers only and reads the time as a 12-hour moment', async () => {
    const { result } = renderHook(() => useIntegrationLogsListConfig(), { wrapper: look(true) });
    expect(result.current.fx).toMatchObject({ noun: 'logs', copyable: ['operation', 'workspace'] });
    const timeCol = result.current.columns.find((c) => c.id === 'createdAt')!;
    const Cell = timeCol.cell as (ctx: unknown) => ReactNode;
    render(<>{Cell({ row: { original: LOG } })}</>, { wrapper: look(true) });
    const time = document.querySelector('time')!;
    expect(time.getAttribute('title')).toBe('5 Nov 2026, 3:04 pm');
    expect(time.closest('[data-fx-h2c]')).not.toBeNull();
  });

  it('with the switch off the config keeps the old time cell', async () => {
    const { result } = renderHook(() => useIntegrationLogsListConfig(), { wrapper: look(false) });
    const Cell = result.current.columns.find((c) => c.id === 'createdAt')!.cell as (ctx: unknown) => ReactNode;
    render(<>{Cell({ row: { original: LOG } })}</>, { wrapper: look(false) });
    expect(document.querySelector('time')).toBeNull();
    expect(document.querySelector('[data-fx-h2c]')).toBeNull();
    expect(document.body.textContent).toMatch(/2026/);
  });
});

describe('one log under the switch', () => {
  it('plain text values; Hold to Copy on identifiers and the time, never the error or payloads', async () => {
    render(<LogDetailView logId="log-2" />, { wrapper: look(true) });
    const error = await screen.findByTestId('log-error');
    expect(error.closest('[data-fx-h2c]')).toBeNull();

    const copyable = Array.from(document.querySelectorAll('[data-fx-h2c]')).map((el) => el.textContent);
    expect(copyable).toEqual([
      'POST /messages',
      'key-42',
      'trc-7f3a',
      'wamid.HBgM',
      '5 Nov 2026, 3:04 pm',
      'template_paused',
    ]);

    // The payloads stay the same code blocks and never copy.
    fireEvent.mouseDown(screen.getByRole('tab', { name: /Payloads/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Payloads/ }));
    const payload = await screen.findByText(/promo_nov/);
    expect(payload.tagName).toBe('PRE');
    expect(payload.closest('[data-fx-h2c]')).toBeNull();
    expect(within(payload.parentElement!).queryAllByRole('button')).toEqual([]);
    expect(writes()).toEqual([]);
  });
});
