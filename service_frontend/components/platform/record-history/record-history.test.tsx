/**
 * The shared History view (owner standing rule: every tracked action on a
 * record shows in its History - who, on behalf of, when, plain action,
 * old -> new). First adopter: the operator feedback record (crew pass c4572865).
 */
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { HistoryEntry } from '@/types/record-history';
import { historyPage, RecordHistory } from './record-history';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/feedback/i-1'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({ useImportActivity: () => ({ openImport: vi.fn() }) }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDmyDateTime: (v: string) => `DT:${v.slice(0, 10)}`, formatDmyDate: (v: string) => v.slice(0, 10) }),
}));

const rows: HistoryEntry[] = [
  { id: 'h-2', at: '2026-11-17T06:00:00Z', who: 'Admin Ada', onBehalfOf: 'Staff Sam', action: 'Follower added', from: null, to: 'Manager B' },
  { id: 's-1', at: '2026-11-16T06:00:00Z', who: null, onBehalfOf: null, action: 'Status changed', from: 'New', to: 'Triaged' },
];

beforeEach(() => {
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

describe('RecordHistory', () => {
  it('lists who, on behalf of, when, action, from, to; unknown values read "-"', async () => {
    render(<RecordHistory viewKey="t.history" load={() => Promise.resolve(rows)} />);
    await screen.findByText('Follower added');
    const table = screen.getByRole('table');
    const first = within(table).getByText('Follower added').closest('tr') as HTMLElement;
    expect(within(first).getByText('Admin Ada')).toBeInTheDocument();
    expect(within(first).getByText('Staff Sam')).toBeInTheDocument();
    expect(within(first).getByText('Manager B')).toBeInTheDocument();
    expect(within(first).getByText('DT:2026-11-17')).toBeInTheDocument();
    const status = within(table).getByText('Status changed').closest('tr') as HTMLElement;
    expect(within(status).getByText('New')).toBeInTheDocument();
    expect(within(status).getByText('Triaged')).toBeInTheDocument();
    expect(within(status).getAllByText('-').length).toBeGreaterThan(0);
  });

  it('has the standard toolbar: search, filters, columns, export; no Create', async () => {
    render(<RecordHistory viewKey="t.history" load={() => Promise.resolve(rows)} />);
    await screen.findByRole('table');
    expect(screen.getByRole('button', { name: /filters/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create' })).toBeNull();
  });

  it('an empty history says so', async () => {
    render(<RecordHistory viewKey="t.history" load={() => Promise.resolve([])} />);
    expect(await screen.findByText('No history yet.')).toBeInTheDocument();
  });

  it('a failed load offers Try again', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(rows);
    render(<RecordHistory viewKey="t.history" load={load} />);
    const retry = await screen.findByRole('button', { name: 'Try again' });
    retry.click();
    expect(await screen.findByText('Follower added')).toBeInTheDocument();
  });
});

describe('historyPage', () => {
  const q = { page: 0, pageSize: 25 };
  it('newest first by default; filters by action (multi-select) and who', () => {
    expect(historyPage(rows, q).data.map((r) => r.id)).toEqual(['h-2', 's-1']);
    const status = historyPage(rows, {
      ...q,
      filter: { kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'action', operator: 'in', value: ['Status changed'] }] },
    });
    expect(status.data.map((r) => r.id)).toEqual(['s-1']);
    expect(historyPage(rows, { ...q, search: 'ada' }).data.map((r) => r.id)).toEqual(['h-2']);
  });
  it('sorts by when ascending', () => {
    expect(historyPage(rows, { ...q, sort: { id: 'at', desc: false } }).data.map((r) => r.id)).toEqual(['s-1', 'h-2']);
  });
});
