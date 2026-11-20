/**
 * Plan 63 (AC-63-34, 36, RED): the AutoCount calls page on the REAL `ResourceList` (only the
 * boundaries are mocked: services, session, router). A row click opens a centred dialog with the
 * request JSON and the response body. `page.tsx` does not exist yet - the dynamic import fails.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/calls'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: ['autocount.sync.read'], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({ useImportActivity: () => ({ openImport: vi.fn() }) }));

const ROW = {
  id: 'call-1', createdAt: '2026-11-05T07:04:00Z', companyId: 'co-1', companyName: 'Alpha Co', book: 'db3',
  actingUserId: 'u1', actingUserName: 'Una', method: 'PUT', path: '/EditSalesOrderbydockey', docType: 'SO',
  docNo: 'SO-100', outcome: 'http_error', responseStatus: 500, durationMs: 42, errorCode: null, requestId: 'req-100',
};
const DETAIL = {
  ...ROW,
  requestJson: { DocKey: 100, Remark1: 'sent-remark' },
  responseBody: 'vendor said boom-body',
};

const listCalls = vi.fn();
const getCall = vi.fn();
const getCallFilterOptions = vi.fn();
const known: Record<string, unknown> = { listCalls, getCall, getCallFilterOptions };
vi.mock('@/services/autocount-service', () => ({
  autocountService: new Proxy(
    {},
    {
      get: (_t, prop: string) =>
        prop in known ? known[prop] : vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }),
    },
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  listCalls.mockResolvedValue({ data: [ROW], total: 1, page: 0 });
  getCall.mockResolvedValue(DETAIL);
  getCallFilterOptions.mockResolvedValue({ books: ['db3'], docTypes: ['SO'], outcomes: ['http_error'], persons: [{ id: 'u1', name: 'Una' }] });
});

async function renderPage() {
  const mod = await import('./page');
  const Page = mod.default;
  return render(<Page />);
}

describe('AutoCount calls page (AC-63-34..36)', () => {
  it('titles the page and lists the call with plain words and the dd/mm/yyyy time', async () => {
    await renderPage();
    expect(await screen.findByText('SO-100')).toBeInTheDocument();
    expect(screen.getAllByText(/AutoCount calls/i).length).toBeGreaterThan(0);
    expect(screen.getByText('Refused by AutoCount')).toBeInTheDocument();
    expect(screen.getByText('05/11/2026, 3:04 pm')).toBeInTheDocument();
    expect(screen.queryByText('http_error')).not.toBeInTheDocument();
  });

  it('is a log: it offers no Create button', async () => {
    await renderPage();
    await screen.findByText('SO-100');
    expect(screen.queryByRole('button', { name: /create/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^new\b/i })).not.toBeInTheDocument();
  });

  it('clicking a row opens a centred dialog with the request JSON and the response body', async () => {
    await renderPage();
    await userEvent.click(await screen.findByText('SO-100'));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(getCall).toHaveBeenCalledWith('call-1'));
    expect(await within(dialog).findByText(/sent-remark/)).toBeInTheDocument();
    expect(within(dialog).getByText(/boom-body/)).toBeInTheDocument();
  });

  it('a row never navigates away (the log has no detail page)', async () => {
    const nav = await import('next/navigation');
    const push = vi.fn();
    vi.mocked(nav.useRouter).mockReturnValue({ push, replace: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof nav.useRouter>);
    await renderPage();
    await userEvent.click(await screen.findByText('SO-100'));
    await screen.findByRole('dialog');
    expect(push).not.toHaveBeenCalled();
  });
});
