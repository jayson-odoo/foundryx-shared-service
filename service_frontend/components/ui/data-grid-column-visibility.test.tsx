/**
 * AC-15-04 - the Columns popover lists DISPLAY-ONLY columns (id + cell, no
 * accessor). `enableHiding !== false` is the only rule; the old
 * `accessorFn !== undefined` predicate left the ideas list toggle empty.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table';
import { DataGridColumnVisibility } from './data-grid-column-visibility';

interface Row {
  id: string;
}

const columns: ColumnDef<Row>[] = [
  { id: 'select', header: () => null, cell: () => 'x', enableHiding: false },
  { id: 'problem', header: () => 'Idea', cell: () => 'a', meta: { headerTitle: 'Idea' } },
  { id: 'submitter', header: () => 'Submitter', cell: () => 'b', meta: { headerTitle: 'Submitter' } },
  { id: 'submitted', header: () => 'Submitted', cell: () => 'c', meta: { headerTitle: 'Submitted' } },
];

function Harness() {
  const table = useReactTable({ data: [{ id: '1' }], columns, getCoreRowModel: getCoreRowModel() });
  return <DataGridColumnVisibility table={table} trigger={<button type="button">Columns</button>} />;
}

describe('DataGridColumnVisibility - display-only columns (AC-15-04)', () => {
  it('lists a checkbox per hideable column and none for enableHiding:false', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Columns' }));
    const items = await screen.findAllByRole('menuitemcheckbox');
    expect(items.map((i) => i.textContent?.trim())).toEqual(['Idea', 'Submitter', 'Submitted']);
    expect(screen.queryByText('select')).not.toBeInTheDocument();
  });
});
