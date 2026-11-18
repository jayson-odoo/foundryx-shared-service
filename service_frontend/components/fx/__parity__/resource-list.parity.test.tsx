/**
 * Switch-off parity: ResourceList with a stub fetcher, and DataGridTable on
 * its own (see parity-utils.ts).
 */
import { useMemo } from 'react';
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import { Trash2 } from 'lucide-react';
import { describe, expect, it, vi } from 'vitest';
import { DataGrid } from '@/components/ui/data-grid';
import { DataGridTable } from '@/components/ui/data-grid-table';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';
import { parityHtml } from './parity-utils';

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
  email: string;
}

const rows: Row[] = [
  { id: 'r1', name: 'Alpha Tan', email: 'alpha@example.com' },
  { id: 'r2', name: 'Bravo Lim', email: 'bravo@example.com' },
  { id: 'r3', name: 'Charlie Ng', email: 'charlie@example.com' },
];

const columns: ColumnDef<Row>[] = [
  {
    id: 'name',
    accessorKey: 'name',
    header: 'Name',
    cell: ({ row }) => row.original.name,
  },
  {
    id: 'email',
    accessorKey: 'email',
    header: 'Email',
    cell: ({ row }) => row.original.email,
  },
];

function config(): ResourceListConfig<Row> {
  return {
    viewKey: 'parity.users',
    columns,
    getRowId: (row) => row.id,
    rowHref: (row) => `/user-management/users/${row.id}`,
    fetcher: async () => ({ data: rows, total: rows.length, page: 1 }),
    exporter: async () => '',
    filterFields: [{ field: 'name', label: 'Name', type: 'text' }],
    exportColumns: [{ id: 'name', label: 'Name' }],
    actions: [
      {
        id: 'trash',
        label: 'Trash',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true },
        run: vi.fn(),
      },
    ],
    createLabel: 'Add user',
    onCreate: vi.fn(),
  };
}

describe('parity (switch off): ResourceList', () => {
  it('loaded list with search, filter, actions and rows', async () => {
    const { container } = render(<ResourceList config={config()} />);
    await screen.findByText('Charlie Ng');
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

function GridHarness() {
  const cols = useMemo(() => columns, []);
  const table = useReactTable({
    data: rows,
    columns: cols,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <DataGrid
      table={table}
      recordCount={rows.length}
      rowHref={(row) => `/records/${row.id}`}
    >
      <DataGridTable />
    </DataGrid>
  );
}

describe('parity (switch off): DataGridTable', () => {
  it('renders the header and body rows as before', () => {
    const { container } = render(<GridHarness />);
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
