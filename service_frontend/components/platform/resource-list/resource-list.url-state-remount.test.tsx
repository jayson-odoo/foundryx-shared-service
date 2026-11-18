/**
 * Crew pass ffa60e3f (#259): a list that is unmounted and mounted again on the
 * same page (Lead Capture Delivery: Pull only, then "Push to my system")
 * restored the PAGE-LOAD search / sort / filter instead of the current ones.
 *
 * Cause: the list wrote its state with `history.replaceState(history.state, ...)`.
 * Next's patched `replaceState` treats a state carrying its own `__NA` marker
 * as the router's own call and does NOT update `useSearchParams()`, so the
 * remount's restore read the page-load `ctx`. The stand-in below applies the
 * same rule as Next (`app-router.js`): a write without `__NA` updates the
 * search params the next mount reads.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { decodeListQuery, encodeListQuery } from '@/lib/list-context';
import { ResourceList } from './resource-list';
import type { ResourceListConfig } from './types';

let routerSearch = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() })),
  useSearchParams: vi.fn(() => routerSearch),
  usePathname: vi.fn(() => '/records'),
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
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

interface Row {
  id: string;
  name: string;
}

const fetcher = vi.fn(async () => ({ data: [{ id: 'r1', name: 'Alpha' }], total: 1, page: 0 }));

function config(): ResourceListConfig<Row> {
  const columns: ColumnDef<Row>[] = [{ id: 'name', header: 'Name', cell: ({ row }) => row.original.name }];
  return {
    viewKey: 'records.list',
    columns,
    getRowId: (r) => r.id,
    rowHref: () => '#',
    fetcher,
    exporter: async () => '',
    filterFields: [],
    exportColumns: [],
    actions: [],
    searchPlaceholder: 'Search records',
    urlState: true,
  };
}

const realReplaceState = window.history.replaceState.bind(window.history);

beforeEach(() => {
  vi.clearAllMocks();
  const loadQuery = { page: 0, pageSize: 25, search: 'old', sort: null, filter: null, statusView: 'active' as const };
  const ctx = encodeListQuery(loadQuery);
  routerSearch = new URLSearchParams({ ctx });
  // The page as Next leaves it: its own state marker on the history entry.
  realReplaceState({ __NA: true }, '', `/records?ctx=${encodeURIComponent(ctx)}`);
  // Next's rule: a write carrying `__NA` is the router's own; any other write
  // updates what `useSearchParams()` returns.
  vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
    const marker = (data as { __NA?: boolean } | null)?.__NA;
    if (!marker && url) routerSearch = new URL(String(url), window.location.href).searchParams;
    realReplaceState({ ...(data as object), __NA: true }, unused, url);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResourceList URL state survives a remount', () => {
  it('a list mounted again (Pull only -> Push) restores the CURRENT search, not the page-load one', async () => {
    const user = userEvent.setup();
    const first = render(<ResourceList config={config()} hideHeader restoreFromCtx />);
    const search = await screen.findByPlaceholderText('Search records');
    expect(search).toHaveValue('old');

    await user.clear(search);
    await user.type(search, 'new');
    // The list has written its new state to the address bar.
    await waitFor(() => expect(decodeListQuery(new URLSearchParams(window.location.search).get('ctx'))?.search).toBe('new'));

    // Pull only: the list goes away; "Push to my system": it comes back.
    first.unmount();
    await act(async () => {
      render(<ResourceList config={config()} hideHeader restoreFromCtx />);
    });
    expect(await screen.findByPlaceholderText('Search records')).toHaveValue('new');
  });
});
