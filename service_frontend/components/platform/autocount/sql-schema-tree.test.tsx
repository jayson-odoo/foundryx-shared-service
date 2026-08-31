import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SqlSchemaTree } from './sql-schema-tree';
import type { AutocountSqlSchema } from '@/types/autocount';

const SCHEMA: AutocountSqlSchema = {
  connectionId: 'conn-sql-1',
  dialect: 'mssql',
  database: 'AED_Sorento_2024',
  schemas: [
    {
      name: 'dbo',
      tables: [
        {
          name: 'Debtor',
          columns: [
            { name: 'AccNo', type: 'varchar(12)' },
            { name: 'CompanyName', type: 'nvarchar(100)' },
          ],
        },
        { name: 'Creditor', columns: [{ name: 'AccNo', type: 'varchar(12)' }] },
      ],
    },
    {
      name: 'audit',
      tables: [{ name: 'ChangeLog', columns: [{ name: 'Id', type: 'bigint' }] }],
    },
  ],
  introspectedAt: '2026-08-30T00:00:00Z',
};

function renderTree(overrides: Partial<React.ComponentProps<typeof SqlSchemaTree>> = {}) {
  const onInsertQuery = vi.fn();
  const onRefresh = vi.fn();
  render(
    <SqlSchemaTree
      schema={SCHEMA}
      isLoading={false}
      error={null}
      onRefresh={onRefresh}
      onInsertQuery={onInsertQuery}
      canInsert
      {...overrides}
    />,
  );
  return { onInsertQuery, onRefresh };
}

describe('SqlSchemaTree', () => {
  it('lists tables only (no columns) with the first schema open', () => {
    renderTree();
    expect(screen.getByText('AED_Sorento_2024')).toBeInTheDocument();
    expect(screen.getByText('Debtor')).toBeInTheDocument();
    expect(screen.getByText('Creditor')).toBeInTheDocument();
    // Second schema starts collapsed; columns never render in the tree.
    expect(screen.queryByText('ChangeLog')).not.toBeInTheDocument();
    expect(screen.queryByText('CompanyName')).not.toBeInTheDocument();
  });

  it('Expand all opens every schema, then reads Collapse all', () => {
    renderTree();
    fireEvent.click(screen.getByRole('button', { name: /expand all/i }));
    expect(screen.getByText('ChangeLog')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /collapse all/i }));
    expect(screen.queryByText('Debtor')).not.toBeInTheDocument();
  });

  it('search filters tables across schemas regardless of collapse state', () => {
    renderTree();
    fireEvent.change(screen.getByLabelText('Search tables'), { target: { value: 'change' } });
    expect(screen.getByText('ChangeLog')).toBeInTheDocument();
    expect(screen.queryByText('Debtor')).not.toBeInTheDocument();
  });

  it('clicking a table opens its columns side panel with the starter action', () => {
    const { onInsertQuery } = renderTree();
    fireEvent.click(screen.getByText('Debtor'));
    const panel = screen.getByTestId('sql-columns-panel');
    expect(panel).toHaveTextContent('AccNo');
    expect(panel).toHaveTextContent('nvarchar(100)');
    fireEvent.click(screen.getByTestId('sql-insert-starter'));
    expect(onInsertQuery).toHaveBeenCalledWith('dbo', 'Debtor');
  });

  it('withholds the starter action in read mode', () => {
    renderTree({ canInsert: false });
    fireEvent.click(screen.getByText('Debtor'));
    expect(screen.getByTestId('sql-columns-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('sql-insert-starter')).not.toBeInTheDocument();
  });

  it('renders loading + error states and wires Refresh', () => {
    const { onRefresh } = renderTree({ schema: null, isLoading: true });
    expect(screen.getByTestId('sql-schema-loading')).toBeInTheDocument();
    render(
      <SqlSchemaTree
        schema={null}
        isLoading={false}
        error="Could not connect to the database: connection refused."
        onRefresh={onRefresh}
        onInsertQuery={vi.fn()}
        canInsert
      />,
    );
    expect(screen.getByTestId('sql-schema-error')).toHaveTextContent('connection refused');
    fireEvent.click(screen.getAllByRole('button', { name: /refresh schema/i })[1]);
    expect(onRefresh).toHaveBeenCalled();
  });
});
