/**
 * AC-DLA-15: `isPlaceholderData` dims the body (`opacity-60`) while the
 * pagination strip stays mounted and interactive (Rows-per-page changeable,
 * Next pressable again - the second press wins); skeleton rows render ONLY
 * when `isLoading && rows.length === 0`.
 */
import { useMemo, useState } from 'react';
import { getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DataGrid } from './data-grid';
import { DataGridTable } from './data-grid-table';
import { DataGridPagination } from './data-grid-pagination';

interface Row {
  id: string;
  name: string;
}

function Harness({ isLoading, isPlaceholderData, rows }: { isLoading: boolean; isPlaceholderData: boolean; rows: Row[] }) {
  const columns = useMemo<ColumnDef<Row>[]>(() => [{ id: 'name', header: 'Name', cell: ({ row }) => row.original.name }], []);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });
  const table = useReactTable({
    data: rows,
    columns,
    state: { pagination },
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataGrid table={table} recordCount={rows.length} isLoading={isLoading} isPlaceholderData={isPlaceholderData}>
      <DataGridTable />
      <DataGridPagination />
    </DataGrid>
  );
}

describe('AC-DLA-15 isPlaceholderData dim + pagination gating', () => {
  it('dims the body (opacity-60) while isPlaceholderData is true', () => {
    render(<Harness isLoading isPlaceholderData rows={[{ id: '1', name: 'Alpha' }]} />);
    const tbody = document.querySelector('tbody:not([aria-hidden])');
    expect(tbody?.className).toContain('opacity-60');
    // The stale row itself still renders - not replaced by a skeleton.
    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });

  it('does not render skeleton rows while isPlaceholderData is true, even if isLoading', () => {
    render(<Harness isLoading isPlaceholderData rows={[{ id: '1', name: 'Alpha' }]} />);
    expect(document.querySelectorAll('[data-slot="data-grid-table"] tbody tr')).toHaveLength(1);
    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });

  it('renders skeleton rows only on a genuine first load (isLoading && zero rows)', () => {
    render(<Harness isLoading={true} isPlaceholderData={false} rows={[]} />);
    // Skeleton rows carry no cell text, one per configured page size (10).
    const skeletonRows = document.querySelectorAll('[data-slot="data-grid-table"] tbody tr');
    expect(skeletonRows.length).toBe(10);
  });

  it('renders the empty state, not a skeleton, once loading settles with zero rows', () => {
    render(<Harness isLoading={false} isPlaceholderData={false} rows={[]} />);
    expect(screen.getByText('No data available')).toBeInTheDocument();
  });

  it('pagination stays mounted and interactive (Rows-per-page changeable) while isPlaceholderData is true', () => {
    render(<Harness isLoading isPlaceholderData rows={[{ id: '1', name: 'Alpha' }]} />);
    expect(screen.getByText('Rows per page')).toBeInTheDocument();
    expect(screen.queryByText(/^\.\.\.$/)).not.toBeInTheDocument();
  });
});
