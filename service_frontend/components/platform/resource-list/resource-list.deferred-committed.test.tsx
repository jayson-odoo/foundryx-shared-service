/**
 * FEEDBACK-SUBSCRIBE crew pass 4025e5e9: a grace-window (deferred) action run
 * from the right-click / long-press row menu or the bulk bar must tell the page
 * when it commits (`config.onDeferredCommitted`), so a list built from data the
 * page holds (BR > Feedback tab) refreshes without a reload.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { DataGridTableRowSelect } from '@/components/ui/data-grid-table';
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
// The grace window commits as soon as it starts here.
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: (opts: { onCommitted?: () => void }) => ({
    state: { status: 'idle' },
    dimEntityIds: [],
    start: vi.fn(async (_key: string, entities: { entityId: string }[]) => {
      setTimeout(() => opts.onCommitted?.(), 0);
      return { commitAt: new Date().toISOString(), windowSeconds: 5, failedCount: 0, parkedEntityIds: entities.map((e) => e.entityId) };
    }),
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
}));

interface Row {
  id: string;
  name: string;
}
const rows: Row[] = [{ id: 'r1', name: 'Alpha' }];

function config(onDeferredCommitted: () => void): ResourceListConfig<Row> {
  const columns: ColumnDef<Row>[] = [
    { id: 'select', header: () => null, cell: ({ row }) => <DataGridTableRowSelect row={row} />, size: 40 },
    { id: 'name', header: 'Name', cell: ({ row }) => row.original.name },
  ];
  return {
    viewKey: 'records.list',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher: async () => ({ data: rows, total: rows.length, page: 0 }),
    exporter: async () => '',
    filterFields: [],
    exportColumns: [],
    actions: [
      {
        id: 'unlink',
        label: 'Unlink',
        surfaces: { row: true, bulk: true },
        deferred: { actionKey: 'x.unlink', entityType: 'x_link' },
      },
    ],
    onDeferredCommitted,
  };
}

beforeEach(() => vi.clearAllMocks());

describe('ResourceList onDeferredCommitted', () => {
  it('fires after a right-click row action commits', async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    render(<ResourceList config={config(done)} hideHeader />);
    const row = (await screen.findByText('Alpha')).closest('tr') as HTMLElement;
    await user.pointer({ keys: '[MouseRight]', target: row });
    await user.click(await screen.findByRole('menuitem', { name: 'Unlink' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
  });

  it('fires after a bulk action commits', async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    render(<ResourceList config={config(done)} hideHeader />);
    await screen.findByText('Alpha');
    await user.click(screen.getAllByRole('checkbox', { name: /select row/i })[0]);
    await user.click(await screen.findByRole('button', { name: 'Bulk actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Unlink' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
  });
});
