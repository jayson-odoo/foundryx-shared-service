/**
 * Switch-off parity for the list pieces slice F3a branches that F1's harness
 * did not already pin (see parity-utils.ts): ResourceList with titled,
 * sortable column headers, segments, a card renderer, row reorder and an
 * embedded (header-less) list, and DataGridColumnHeader on its own. Recorded
 * on the code before any F3a change.
 */
import { useMemo } from 'react';
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { parityHtml as baseParityHtml } from './parity-utils';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
    return seen.get(id) as string;
  });
}

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/user-management/users'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: [] } },
    status: 'authenticated',
  }),
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
  status: string;
  createdAt: string;
}

const rows: Row[] = [
  { id: 'r1', name: 'Alpha Tan', status: 'Active', createdAt: '2026-11-01' },
  { id: 'r2', name: 'Bravo Lim', status: 'Invited', createdAt: '2026-11-02' },
  { id: 'r3', name: 'Charlie Ng', status: 'Active', createdAt: '2026-11-03' },
];

const columns: ColumnDef<Row>[] = [
  {
    id: 'name',
    accessorKey: 'name',
    header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
    cell: ({ row }) => row.original.name,
    meta: { headerTitle: 'Name' },
  },
  {
    id: 'status',
    accessorKey: 'status',
    header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
    cell: ({ row }) => row.original.status,
    enableSorting: false,
    meta: { headerTitle: 'Status' },
  },
  {
    id: 'createdAt',
    accessorKey: 'createdAt',
    header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
    cell: ({ row }) => row.original.createdAt,
    meta: { headerTitle: 'Created' },
  },
];

function config(extra: Partial<ResourceListConfig<Row>> = {}): ResourceListConfig<Row> {
  return {
    viewKey: 'parity.f3a',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/records/${row.id}`,
    fetcher: async () => ({ data: rows, total: 312, page: 0 }),
    filterFields: [
      { field: 'name', label: 'Name', type: 'text' },
      {
        field: 'status',
        label: 'Status',
        type: 'enum',
        options: [
          { label: 'Active', value: 'Active' },
          { label: 'Invited', value: 'Invited' },
        ],
      },
      { field: 'createdAt', label: 'Created', type: 'date' },
    ],
    exportColumns: [],
    actions: [],
    searchPlaceholder: 'Search records',
    ...extra,
  };
}

describe('parity (switch off): ResourceList (F3a cases)', () => {
  it('titled sortable headers, many pages, no export', async () => {
    const { container } = render(<ResourceList config={config()} />);
    await screen.findByText('Charlie Ng');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('segments and search hints', async () => {
    const { container } = render(
      <ResourceList
        config={config({
          segments: [
            { id: 'all', label: 'All' },
            { id: 'mine', label: 'Mine' },
          ],
          searchHints: ['Name', 'Email'],
        })}
      />,
    );
    await screen.findByText('Charlie Ng');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('embedded list with a card renderer and its own Create', async () => {
    const { container } = render(
      <ResourceList
        hideHeader
        config={config({
          cardRender: (row) => <span>{row.name}</span>,
          createLabel: 'Add record',
          onCreate: vi.fn(),
        })}
      />,
    );
    await screen.findByText('Charlie Ng');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('row reorder list', async () => {
    const { container } = render(
      <ResourceList
        config={config({ rowReorder: { onReorder: vi.fn() } })}
      />,
    );
    await screen.findByText('Charlie Ng');
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

function HeaderHarness() {
  const cols = useMemo(() => columns, []);
  const table = useReactTable({
    data: rows,
    columns: cols,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
    state: { sorting: [{ id: 'name', desc: true }] },
    manualSorting: true,
  });
  return (
    <DataGrid
      table={table}
      recordCount={rows.length}
      tableLayout={{ columnsMovable: false, columnsResizable: false }}
    >
      <DataGridTable />
    </DataGrid>
  );
}

describe('parity (switch off): DataGridColumnHeader', () => {
  it('renders the sorted, plain and unsortable headers as before', () => {
    const { container } = render(<HeaderHarness />);
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
