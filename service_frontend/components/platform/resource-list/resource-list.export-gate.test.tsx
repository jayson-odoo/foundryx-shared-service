/**
 * T7 fix round 1, item 6b - the Export button used to render unconditionally
 * even when a list had `exportColumns: []` + a no-op `exporter: async () =>
 * ''` (imports, jobs, every embedded related list) - clicking it downloaded
 * an EMPTY file. `exporter` is now optional and the shell hides the Export
 * button entirely (both the default toolbar and the bulk-selection toolbar)
 * whenever there is nothing to export (`exportColumns.length === 0` or no
 * `exporter` supplied).
 */
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
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

describe('T7 fix round 1 item 6b - Export button gated on exportColumns', () => {
  it('no Export button when exportColumns is empty (no exporter supplied)', async () => {
    render(<ResourceList config={baseConfig()} />);
    await screen.findByRole('table');
    expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument();
  });

  it('no Export button when exportColumns is empty even if a stray exporter is supplied', async () => {
    render(<ResourceList config={baseConfig({ exporter: async () => '' })} />);
    await screen.findByRole('table');
    expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument();
  });

  it('Export button renders when exportColumns is non-empty and an exporter is supplied', async () => {
    render(
      <ResourceList
        config={baseConfig({
          exportColumns: [{ id: 'name', label: 'Name' }],
          exporter: async () => 'name\nAlpha\nBravo',
        })}
      />,
    );
    await screen.findByRole('table');
    expect(screen.getByRole('button', { name: /export/i })).toBeInTheDocument();
  });

  // The bulk-selection toolbar's Export button is gated by the SAME
  // `canExport` flag as the default toolbar's (both read
  // `config.exportColumns.length > 0 && Boolean(config.exporter)` in
  // resource-list.tsx) - not re-exercised here via a row-selection
  // interaction (no `select` column wired into this minimal test config),
  // since it is the identical boolean, not a second code path to drift.
});
