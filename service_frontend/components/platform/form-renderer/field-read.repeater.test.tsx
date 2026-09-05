/**
 * AC-DLA-56 (T7) - RepeaterRead (a form submission's repeater answer, read
 * mode) migrated off the raw @/components/ui/table primitive onto
 * DataGrid + DataGridTable. Column headers come from the repeater's
 * sub-fields; cells format yesno/empty the same as before.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FieldRead } from './field-read';
import type { FormField } from '@/types/forms';

const field: FormField = {
  id: 'f1',
  key: 'line_items',
  type: 'repeater',
  label: 'Line items',
  repeater: {
    fields: [
      { id: 's1', key: 'item', type: 'text', label: 'Item' },
      { id: 's2', key: 'inStock', type: 'yesno', label: 'In stock' },
    ],
  },
};

describe('RepeaterRead (via FieldRead)', () => {
  it('renders a DataGrid with a column per sub-field and formatted cell values', () => {
    render(
      <FieldRead
        field={field}
        value={[
          { item: 'Widget', inStock: true },
          { item: 'Gadget', inStock: false },
        ]}
      />,
    );
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Item' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'In stock' })).toBeInTheDocument();
    expect(screen.getByText('Widget')).toBeInTheDocument();
    expect(screen.getByText('Gadget')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getByText('No')).toBeInTheDocument();
  });

  it('an empty cell renders the em-dash placeholder, not a blank', () => {
    render(<FieldRead field={field} value={[{ item: '', inStock: null }]} />);
    const emDashes = screen.getAllByText('-');
    expect(emDashes.length).toBeGreaterThanOrEqual(2);
  });

  it('zero rows renders the muted placeholder instead of an empty grid', () => {
    render(<FieldRead field={field} value={[]} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('-')).toBeInTheDocument();
  });
});
