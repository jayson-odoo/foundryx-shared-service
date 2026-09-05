/**
 * AC-DLA-45: a row parked under a deferred action dims via `data-pending`
 * (the class carries `data-[pending=true]:opacity-50` on the same
 * opacity transition AC-DLA-30's `data-returned` uses), driven by
 * `lib/pending-entity-store.ts` - imperative DOM toggling, matching
 * `useRestoreReturnedRow`'s pattern (no React re-render per tick).
 */
import { useMemo } from 'react';
import { getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useSearchParams } from 'next/navigation';
import { DataGrid } from './data-grid';
import { DataGridTable } from './data-grid-table';
import {
  _resetPendingEntityStoreForTests,
  trackPendingEntities,
  untrackPendingEntities,
} from '@/lib/pending-entity-store';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [
  { id: '1', name: 'Alpha' },
  { id: '2', name: 'Bravo' },
  { id: '3', name: 'Charlie' },
];

function Harness() {
  const columns = useMemo<ColumnDef<Row>[]>(
    () => [{ id: 'name', header: 'Name', cell: ({ row }) => row.original.name }],
    [],
  );
  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <DataGrid table={table} recordCount={rows.length}>
      <DataGridTable />
    </DataGrid>
  );
}

function bodyRows() {
  return screen.getAllByRole('row').slice(1);
}

beforeEach(() => {
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
  _resetPendingEntityStoreForTests();
});

describe('AC-DLA-45 pending-row dim', () => {
  it('a tracked entity id dims its matching row via data-pending', () => {
    render(<Harness />);
    act(() => trackPendingEntities(['2']));
    expect(bodyRows()[1]).toHaveAttribute('data-pending', 'true');
    expect(bodyRows()[0]).not.toHaveAttribute('data-pending');
    expect(bodyRows()[2]).not.toHaveAttribute('data-pending');
  });

  it('untracking clears the attribute', () => {
    render(<Harness />);
    act(() => trackPendingEntities(['1']));
    expect(bodyRows()[0]).toHaveAttribute('data-pending', 'true');
    act(() => untrackPendingEntities(['1']));
    expect(bodyRows()[0]).not.toHaveAttribute('data-pending');
  });

  it('a bulk park dims every selected row (D13)', () => {
    render(<Harness />);
    act(() => trackPendingEntities(['1', '2', '3']));
    for (const row of bodyRows()) expect(row).toHaveAttribute('data-pending', 'true');
  });

  it('the opacity class is data-attribute driven', () => {
    render(<Harness />);
    expect(bodyRows()[0].className).toContain('data-[pending=true]:opacity-50');
  });
});
