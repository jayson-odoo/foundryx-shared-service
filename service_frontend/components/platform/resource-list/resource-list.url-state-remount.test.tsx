/**
 * Crew pass ffa60e3f (#259): a list that is unmounted and mounted again on the
 * same page (Lead Capture Delivery: Pull only, then "Push to my system")
 * restored the PAGE-LOAD search / sort / filter instead of the current ones.
 *
 * Cause: Next's `useSearchParams()` never sees the list's own writes (they
 * carry Next's `__NA` marker, so Next treats them as its own). Writing with a
 * null state instead (9a7a7a34) made Next run a router RESTORE on every list
 * write, which discards a click navigation still loading (crew pass 9a7a7a34).
 * So: the list keeps writing as the router's own entry, and a remount restores
 * from the list's own last write. The stand-in below applies Next's rule
 * (`app-router.js`): a write without `__NA` updates the router's search params
 * (and would dispatch a restore).
 */
import type { ColumnDef } from '@tanstack/react-table';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { decodeListQuery, encodeListQuery } from '@/lib/list-context';
import { ResourceList } from './resource-list';
import type { ResourceListConfig } from './types';

let routerSearch = new URLSearchParams();
let routerRestores = 0;

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

const fetcher = vi.fn();
const oneRow = async () => ({ data: [{ id: 'r1', name: 'Alpha' }], total: 1, page: 0 });

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
let replaceSpy: { mockRestore: () => void } | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  fetcher.mockImplementation(oneRow);
  routerRestores = 0;
  const loadQuery = { page: 0, pageSize: 25, search: 'old', sort: null, filter: null, statusView: 'active' as const };
  const ctx = encodeListQuery(loadQuery);
  routerSearch = new URLSearchParams({ ctx });
  // The page as Next leaves it: its own state marker on the history entry.
  realReplaceState({ __NA: true }, '', `/records?ctx=${encodeURIComponent(ctx)}`);
  // Next's rule: a write carrying `__NA` is the router's own; any other write
  // updates what `useSearchParams()` returns.
  replaceSpy = vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
    const marker = (data as { __NA?: boolean } | null)?.__NA;
    if (!marker && url) {
      routerRestores += 1; // Next: ACTION_RESTORE, which drops a pending navigation
      routerSearch = new URL(String(url), window.location.href).searchParams;
    }
    realReplaceState({ ...(data as object), __NA: true }, unused, url);
  });
});

afterEach(() => {
  replaceSpy?.mockRestore();
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

  it("the list's own address-bar writes never run a router restore (a pending click is never dropped)", async () => {
    const user = userEvent.setup();
    render(<ResourceList config={config()} hideHeader restoreFromCtx />);
    const search = await screen.findByPlaceholderText('Search records');
    await user.clear(search);
    await user.type(search, 'abc');
    await waitFor(() => expect(decodeListQuery(new URLSearchParams(window.location.search).get('ctx'))?.search).toBe('abc'));
    expect(routerRestores).toBe(0);
  });

  it('a different list mounting while the address bar still holds this one (navigation in flight) does not take its state', async () => {
    const user = userEvent.setup();
    const first = render(<ResourceList config={config()} hideHeader restoreFromCtx />);
    const search = await screen.findByPlaceholderText('Search records');
    await user.clear(search);
    await user.type(search, 'mine');
    await waitFor(() => expect(decodeListQuery(new URLSearchParams(window.location.search).get('ctx'))?.search).toBe('mine'));
    first.unmount();
    // The next page's list renders before the address bar moves: the router
    // already knows the NEW url (no ctx).
    routerSearch = new URLSearchParams();
    await act(async () => {
      render(<ResourceList config={{ ...config(), viewKey: 'other.list' }} hideHeader restoreFromCtx />);
    });
    expect(await screen.findByPlaceholderText('Search records')).toHaveValue('');
  });
});
