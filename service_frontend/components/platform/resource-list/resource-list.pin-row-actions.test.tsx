/**
 * Hub connector fix round: `pinRowActions` (opt-in) starts the `actions`
 * column pinned right; off by default nothing is pinned.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
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
  const columns: ColumnDef<Row>[] = [
    { id: 'name', header: 'Name', cell: ({ row }) => row.original.name },
    { id: 'actions', header: () => null, cell: () => <span>row-actions</span>, meta: { reorderable: false } },
  ];
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

describe('ResourceList pinRowActions', () => {
  it('on: the actions cell is pinned right', async () => {
    render(<ResourceList config={baseConfig({ pinRowActions: true })} />);
    const cells = await screen.findAllByText('row-actions');
    expect(cells[0].closest('td')?.getAttribute('data-pinned')).toBe('right');
  });

  it('off (default): nothing is pinned', async () => {
    render(<ResourceList config={baseConfig()} />);
    const cells = await screen.findAllByText('row-actions');
    expect(cells[0].closest('td')?.getAttribute('data-pinned')).toBeNull();
  });
});
