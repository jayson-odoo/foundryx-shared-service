/**
 * Switch-off parity for the AutoCount calls page (Foundryx UIUX slice
 * W3-LOGS, build plan 1.3 and 4): the list, and one call's dialog with its
 * request and response, rendered with the switch OFF. Recorded on the code
 * as it was before the slice; a change that needs one of these snapshots
 * updated is wrong by definition (fix the code, never the snapshot).
 * Generated ids are renamed in order of appearance.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import AutocountCallsPage from '../page';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/calls'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
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

const ROWS = [
  {
    id: 'call-1', createdAt: '2026-11-05T07:04:00Z', companyId: 'co-1', companyName: 'Alpha Co', book: 'db3',
    actingUserId: 'u1', actingUserName: 'Una', method: 'PUT', path: '/EditSalesOrderbydockey', docType: 'SO',
    docNo: 'SO-100', outcome: 'http_error', responseStatus: 500, durationMs: 42, errorCode: null, requestId: 'req-100',
  },
  {
    id: 'call-2', createdAt: '2026-11-05T07:05:00Z', companyId: 'co-1', companyName: 'Alpha Co', book: 'db3',
    actingUserId: null, actingUserName: null, method: 'GET', path: '/GetDebtor', docType: null,
    docNo: null, outcome: 'ok', responseStatus: 200, durationMs: 18, errorCode: null, requestId: 'req-101',
  },
];
const DETAIL = { ...ROWS[0], requestJson: { DocKey: 100, Remark1: 'sent-remark' }, responseBody: '{"error":"boom-body"}' };

vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCalls: vi.fn(async () => ({ data: ROWS, total: ROWS.length, page: 0 })),
    getCall: vi.fn(async () => DETAIL),
    getCallFilterOptions: vi.fn(async () => ({ books: ['db3'], docTypes: ['SO'], outcomes: ['http_error', 'ok'], persons: [{ id: 'u1', name: 'Una' }] })),
    listCompanies: vi.fn(async () => ({ data: [{ id: 'co-1', name: 'Alpha Co', companyName: 'Alpha Co' }], total: 1, page: 0 })),
  },
}));

/** Also masks React 19's `_r_N_` ids, in order of first appearance. */
function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('parity (switch off): AutoCount calls', () => {
  it('list with rows, then one call open', async () => {
    const { container } = render(
      <SettingsProvider>
        <AutocountCallsPage />
      </SettingsProvider>,
    );
    await screen.findByText('SO-100');
    expect(stable(container)).toMatchSnapshot();

    fireEvent.click(screen.getByText('SO-100'));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText(/boom-body/);
    expect(stable(dialog)).toMatchSnapshot();
  });
});
