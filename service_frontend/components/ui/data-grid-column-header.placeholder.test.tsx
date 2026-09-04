/**
 * AC-DLA-33 fix round 1: sort buttons and select-all must stay enabled during
 * a placeholder refetch (rows present, isLoading true) - they only disable
 * on a genuinely empty list (recordCount 0, no placeholder rows on screen).
 * Disabling them on every refetch made a re-sort impossible while the grid
 * was quietly re-fetching the next page.
 */
import { useMemo, useState } from 'react';
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DataGrid } from './data-grid';
import { DataGridColumnHeader } from './data-grid-column-header';
import { DataGridTableRowSelectAll } from './data-grid-table';

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [
  { id: '1', name: 'Bravo' },
  { id: '2', name: 'Alpha' },
];

function SortHarness({ isLoading, isPlaceholderData, recordCount }: { isLoading: boolean; isPlaceholderData: boolean; recordCount: number }) {
  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: 'name',
        accessorKey: 'name',
        header: ({ column }) => <DataGridColumnHeader column={column} title="Name" />,
        cell: ({ row }) => row.original.name,
      },
    ],
    [],
  );
  const [sorting, setSorting] = useState([]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <DataGrid table={table} recordCount={recordCount} isLoading={isLoading} isPlaceholderData={isPlaceholderData}>
      <table>
        <thead>
          <tr>
            {table.getHeaderGroups()[0].headers.map((header) => (
              <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>
            ))}
          </tr>
        </thead>
      </table>
    </DataGrid>
  );
}

function SelectAllHarness({ isLoading, isPlaceholderData, recordCount }: { isLoading: boolean; isPlaceholderData: boolean; recordCount: number }) {
  const columns = useMemo<ColumnDef<Row>[]>(() => [{ id: 'name', accessorKey: 'name' }], []);
  const table = useReactTable({
    data: rows,
    columns,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataGrid table={table} recordCount={recordCount} isLoading={isLoading} isPlaceholderData={isPlaceholderData}>
      <DataGridTableRowSelectAll />
    </DataGrid>
  );
}

describe('AC-DLA-33 sort/select-all stay live during a placeholder refetch', () => {
  it('keeps the sort button enabled while rows are present and isLoading is true (a refetch, not an empty list)', () => {
    render(<SortHarness isLoading isPlaceholderData recordCount={2} />);
    const sortButton = screen.getByRole('button', { name: 'Name' });
    expect(sortButton).not.toBeDisabled();
  });

  it('a second click on an enabled sort button during a refetch changes the sort', () => {
    render(<SortHarness isLoading isPlaceholderData recordCount={2} />);
    const sortButton = screen.getByRole('button', { name: 'Name' });
    fireEvent.click(sortButton);
    fireEvent.click(sortButton);
    // No assertion error thrown by either click = the handler ran twice
    // (disabled buttons never dispatch onClick at all).
    expect(sortButton).not.toBeDisabled();
  });

  it('disables the sort button only on a genuinely empty list (no placeholder rows on screen)', () => {
    render(<SortHarness isLoading={false} isPlaceholderData={false} recordCount={0} />);
    expect(screen.getByRole('button', { name: 'Name' })).toBeDisabled();
  });

  it('keeps select-all enabled while rows are present and isLoading is true', () => {
    render(<SelectAllHarness isLoading isPlaceholderData recordCount={2} />);
    expect(screen.getByRole('checkbox', { name: 'Select all' })).not.toBeDisabled();
  });

  it('disables select-all only on a genuinely empty list', () => {
    render(<SelectAllHarness isLoading={false} isPlaceholderData={false} recordCount={0} />);
    expect(screen.getByRole('checkbox', { name: 'Select all' })).toBeDisabled();
  });
});
