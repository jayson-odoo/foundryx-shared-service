/**
 * AC-DLA-29: `ResourceList` passes `rowHref` (not `onRowClick`) for a
 * navigable config, carrying `ctx` + the row's global index + `from=<rowId>`;
 * `onRowSelect` (inline master-detail) keeps the in-place open instead; a
 * `rowHref` of `'#'`/`''` keeps the opt-out.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import { ResourceList } from './resource-list';
import type { ResourceListConfig } from './types';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/records'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
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

const rows: Row[] = [
  { id: 'r1', name: 'Alpha' },
  { id: 'r2', name: 'Bravo' },
];

function baseConfig(overrides: Partial<ResourceListConfig<Row>> = {}): ResourceListConfig<Row> {
  const columns: ColumnDef<Row>[] = [{ id: 'name', header: 'Name', cell: ({ row }) => row.original.name }];
  return {
    viewKey: 'records.list',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher: async () => ({ data: rows, total: rows.length }),
    exporter: async () => '',
    filterFields: [],
    exportColumns: [],
    actions: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

describe('AC-DLA-29 ResourceList rowHref wiring', () => {
  it('every row anchor carries ctx, the global index (i) and from=<rowId>', async () => {
    render(<ResourceList config={baseConfig()} />);

    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getAllByRole('link')).toHaveLength(2));
    const links = within(table).getAllByRole('link');

    const first = new URL(links[0].getAttribute('href')!, 'http://x');
    expect(first.pathname).toBe('/records/r1');
    expect(first.searchParams.get('ctx')).toBeTruthy();
    expect(first.searchParams.get('i')).toBe('0');
    expect(first.searchParams.get('from')).toBe('r1');

    const second = new URL(links[1].getAttribute('href')!, 'http://x');
    expect(second.pathname).toBe('/records/r2');
    expect(second.searchParams.get('i')).toBe('1');
    expect(second.searchParams.get('from')).toBe('r2');
  });

  it('a rowHref of "#" opts every row out (no link, no rowHref navigation)', async () => {
    render(<ResourceList config={baseConfig({ rowHref: () => '#' })} />);
    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1));
    expect(within(table).queryAllByRole('link')).toHaveLength(0);
  });

  it('a rowHref of "#" opt-out row carries no cursor-pointer (no onRowClick fallback, fix round 1)', async () => {
    render(<ResourceList config={baseConfig({ rowHref: () => '#' })} />);
    const table = await screen.findByRole('table');
    // Wait for a REAL row's own content, not merely "row count > 0" - the
    // loading skeleton (`data-grid-table.tsx`'s `unknownHref` heuristic)
    // intentionally still carries `cursor-pointer` while `rowHref` is
    // configured at the list level (a skeleton row has no `row.original`
    // yet to resolve the opt-out against), and it satisfies a bare
    // `getAllByRole('row').length > 0` check just as well as a real row
    // does. A `waitFor` polling that check alone can resolve during the
    // skeleton's own render pass before the async `fetcher` promise settles
    // and the skeleton unmounts - fast locally, but exposed under CI's
    // `--minWorkers=2 --maxWorkers=2` contention (a slower event loop turn
    // lets the assertion run before that swap happens), so the flake was in
    // the test's own timing, not the component. `findByText` only resolves
    // once the fetched row's own name is on the page, i.e. after the
    // skeleton has already been replaced.
    await screen.findByText(rows[0].name);
    const bodyRows = within(table).getAllByRole('row').slice(1); // drop the header row
    expect(bodyRows.length).toBeGreaterThan(0);
    for (const row of bodyRows) {
      expect(row.className).not.toContain('cursor-pointer');
    }
  });

  it('onRowSelect (inline master-detail) skips rowHref entirely - no anchors rendered', async () => {
    const onRowSelect = vi.fn();
    render(<ResourceList config={baseConfig({ onRowSelect })} />);
    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getAllByRole('row').length).toBeGreaterThan(1));
    expect(within(table).queryAllByRole('link')).toHaveLength(0);
  });
});
