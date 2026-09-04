/**
 * AC-DLA-14: `DataGrid` rowHref link semantics - `tabIndex=0` (NO
 * `role="link"`, fix round 1: it would replace the implicit `row` role for
 * assistive tech), click and Enter/Space push, middle-click opens a new tab,
 * hover prefetches once per href, cells with their own control keep
 * `stopPropagation`-like behaviour (a click on a nested control never
 * navigates the row), and neither `rowHref` nor `onRowClick` set means no
 * pointer cursor.
 */
import { useMemo } from 'react';
import { getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter } from 'next/navigation';
import { DataGrid } from './data-grid';
import { DataGridTable } from './data-grid-table';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
}));

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [
  { id: '1', name: 'Alpha' },
  { id: '2', name: 'Bravo' },
];

function Harness({
  rowHref,
  onRowClick,
}: {
  rowHref?: (row: Row) => string;
  onRowClick?: (row: Row) => void;
}) {
  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <div>
            {row.original.name}
            <button type="button" data-testid={`own-control-${row.original.id}`}>
              edit
            </button>
          </div>
        ),
      },
    ],
    [],
  );
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <DataGrid table={table} recordCount={rows.length} rowHref={rowHref} onRowClick={onRowClick}>
      <DataGridTable />
    </DataGrid>
  );
}

let push: ReturnType<typeof vi.fn>;
let prefetch: ReturnType<typeof vi.fn>;

/** Body rows only - `getAllByRole('row')` includes the header row first. */
function bodyRows() {
  return screen.getAllByRole('row').slice(1);
}

beforeEach(() => {
  push = vi.fn();
  prefetch = vi.fn();
  vi.mocked(useRouter).mockReturnValue({ push, prefetch } as unknown as ReturnType<typeof useRouter>);
});

describe('AC-DLA-14 DataGrid rowHref link semantics', () => {
  it('each linked row stays a table row (no role="link") but carries tabIndex=0', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    const rowsEl = bodyRows();
    expect(rowsEl).toHaveLength(2);
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    for (const row of rowsEl) expect(row).toHaveAttribute('tabindex', '0');
  });

  it('clicking a row pushes its href', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    fireEvent.click(bodyRows()[0]);
    expect(push).toHaveBeenCalledWith('/records/1');
  });

  it('Enter and Space on a focused row push its href', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    const row = bodyRows()[1];
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(push).toHaveBeenCalledWith('/records/2');
    push.mockClear();
    fireEvent.keyDown(row, { key: ' ' });
    expect(push).toHaveBeenCalledWith('/records/2');
  });

  it('middle-click (auxclick button 1) opens a new tab instead of pushing', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    fireEvent(bodyRows()[0], new MouseEvent('auxclick', { bubbles: true, button: 1 }));
    expect(openSpy).toHaveBeenCalledWith('/records/1', '_blank', 'noopener,noreferrer');
    expect(push).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it('pointer-enter prefetches the href once', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    const row = bodyRows()[0];
    fireEvent.pointerEnter(row);
    fireEvent.pointerEnter(row);
    expect(prefetch).toHaveBeenCalledTimes(1);
    expect(prefetch).toHaveBeenCalledWith('/records/1');
  });

  it('clicking a cell-owned control does not navigate the row', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    fireEvent.click(screen.getByTestId('own-control-1'));
    expect(push).not.toHaveBeenCalled();
  });

  it('a linked row carries a visible inset focus ring (the scroller clips an outer ring)', () => {
    render(<Harness rowHref={(row) => `/records/${row.id}`} />);
    for (const row of bodyRows()) {
      expect(row.className).toContain('focus-visible:ring-inset');
      expect(row.className).toContain('focus-visible:ring-2');
    }
  });

  it('neither rowHref nor onRowClick set: no pointer cursor, no tabIndex', () => {
    render(<Harness />);
    const rowsEl = bodyRows();
    for (const row of rowsEl) {
      expect(row.className).not.toContain('cursor-pointer');
      expect(row).not.toHaveAttribute('tabindex');
    }
  });
});
