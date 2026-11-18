/**
 * The AutoCount calls page with the Foundryx UIUX switch on (slice W3-LOGS).
 * A read-only log: it sends nothing in either look. Under the switch the
 * time reads as a 12-hour moment (the full form as its tooltip and in the
 * call's dialog), Hold to Copy sits on the path, document number and request
 * id only, and the request and response blocks are unchanged and never copy.
 *
 * Switch off is pinned by `__parity__/calls.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import AutocountCallsPage from './page';

const net = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchText: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch, apiFetchText: net.apiFetchText };
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
  usePathname: vi.fn(() => '/autocount/calls'),
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
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

const ROW = {
  id: 'call-1', createdAt: '2026-11-05T07:04:00Z', companyId: 'co-1', companyName: 'Alpha Co', book: 'db3',
  actingUserId: 'u1', actingUserName: 'Una', method: 'PUT', path: '/EditSalesOrderbydockey', docType: 'SO',
  docNo: 'SO-100', outcome: 'http_error', responseStatus: 500, durationMs: 42, errorCode: null, requestId: 'req-100',
};
const DETAIL = { ...ROW, requestJson: { DocKey: 100, Remark1: 'sent-remark' }, responseBody: '{"error":"boom-body"}' };

beforeEach(() => {
  net.apiFetch.mockReset();
  net.apiFetchText.mockReset();
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string) => {
    if (path.startsWith('/autocount/calls/filter-options')) return { books: [], docTypes: [], outcomes: [], persons: [] };
    if (path === '/autocount/calls/call-1') return DETAIL;
    if (path.startsWith('/autocount/calls')) return { data: [ROW], total: 1, page: 0 };
    return { data: [], total: 0, page: 0 };
  });
});
afterEach(() => resetPageActionsForTests());

function methods() {
  return net.apiFetch.mock.calls.map(([, init]) => (init as RequestInit | undefined)?.method ?? 'GET');
}

/** Text on screen, without the hidden copies the list measures widths with. */
function shownText(value: string): HTMLElement[] {
  return screen.getAllByText(value).filter((el) => !el.closest('[data-fx-measure-item]'));
}

describe('AutoCount calls under the switch', () => {
  it('moment, copyable identifiers, and the dialog unchanged apart from its 12-hour time', async () => {
    render(<AutocountCallsPage />, { wrapper: look(true) });
    await screen.findAllByText('SO-100');
    for (const value of ['SO-100', 'req-100', '/EditSalesOrderbydockey']) {
      const shown = shownText(value);
      expect(shown.length).toBeGreaterThan(0);
      for (const el of shown) expect(el.closest('[data-fx-h2c]')).not.toBeNull();
    }
    const time = document.querySelector('time')!;
    expect(time.getAttribute('title')).toBe('5 Nov 2026, 3:04 pm');

    fireEvent.click(shownText('Alpha Co')[0]);
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('5 Nov 2026, 3:04 pm')).toBeInTheDocument();
    const request = await within(dialog).findByText(/sent-remark/);
    expect(request.tagName).toBe('PRE');
    expect(request.closest('[data-fx-h2c]')).toBeNull();
    expect(within(dialog).getByText(/boom-body/).closest('[data-fx-h2c]')).toBeNull();

    expect(methods().every((m) => m === 'GET')).toBe(true);
  });
});
