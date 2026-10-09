/**
 * AC-DLA-30: on list mount, when `from` names a row on the current page,
 * `DataGridTable` scrolls it into view (`block: 'center'`) and marks it
 * `data-returned` (the row's class list turns that into a `bg-primary/5`
 * highlight), cleared on the next pointer event.
 */
import { useMemo } from 'react';
import { getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useSearchParams } from 'next/navigation';
import { DataGrid } from './data-grid';
import { DataGridTable } from './data-grid-table';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(),
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
    <DataGrid table={table} recordCount={rows.length} rowHref={(row) => `/records/${row.id}`}>
      <DataGridTable />
    </DataGrid>
  );
}

/** Body rows only - `getAllByRole('row')` includes the header row first. */
function bodyRows() {
  return screen.getAllByRole('row').slice(1);
}

function mockSearchParams(from: string | null) {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(from ? { from } : {}) as unknown as ReturnType<typeof useSearchParams>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AC-DLA-30 Back restores the row', () => {
  it('scrolls the named row into view and marks it data-returned', () => {
    mockSearchParams('2');
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    render(<Harness />);

    const target = bodyRows()[1];
    expect(target).toHaveAttribute('data-row-id', '2');
    expect(target).toHaveAttribute('data-returned', 'true');
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center' });
    // Only the named row is marked.
    expect(bodyRows()[0]).not.toHaveAttribute('data-returned');
    expect(bodyRows()[2]).not.toHaveAttribute('data-returned');
  });

  it('the highlight class is data-attribute driven (bg-primary/5)', () => {
    mockSearchParams('1');
    HTMLElement.prototype.scrollIntoView = vi.fn();
    render(<Harness />);
    expect(bodyRows()[0].className).toContain('data-[returned=true]:bg-primary/5');
  });

  it('clears on the next pointer event', () => {
    mockSearchParams('1');
    HTMLElement.prototype.scrollIntoView = vi.fn();
    render(<Harness />);
    expect(bodyRows()[0]).toHaveAttribute('data-returned', 'true');
    fireEvent.pointerDown(document.body);
    expect(bodyRows()[0]).not.toHaveAttribute('data-returned');
  });

  it('no from param: nothing is marked', () => {
    mockSearchParams(null);
    HTMLElement.prototype.scrollIntoView = vi.fn();
    render(<Harness />);
    for (const row of bodyRows()) expect(row).not.toHaveAttribute('data-returned');
  });

  it('from names a row not on this page: nothing is marked, no throw', () => {
    mockSearchParams('does-not-exist');
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    render(<Harness />);
    for (const row of bodyRows()) expect(row).not.toHaveAttribute('data-returned');
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
