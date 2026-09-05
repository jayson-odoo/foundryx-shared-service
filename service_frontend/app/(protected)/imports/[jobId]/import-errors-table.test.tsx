/**
 * AC-DLA-56 (T7) - the import job's error list migrated off the raw
 * @/components/ui/table primitive onto DataGrid + DataGridTable.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ImportErrorsTable } from './import-errors-table';

describe('ImportErrorsTable (AC-DLA-56)', () => {
  it('renders a DataGrid with Row/Column/Problem columns for every error', () => {
    render(
      <ImportErrorsTable
        errors={[
          { row: 3, column: 'email', message: 'Invalid email format' },
          { row: 7, column: 'roleId', message: 'Unknown role id' },
        ]}
      />,
    );
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Row' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Column' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Problem' })).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('email')).toBeInTheDocument();
    expect(screen.getByText('Invalid email format')).toBeInTheDocument();
    expect(screen.getByText('Unknown role id')).toBeInTheDocument();
  });

  it('renders the empty grid state for zero errors', () => {
    render(<ImportErrorsTable errors={[]} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
