import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SqlPreviewGrid } from './sql-preview-grid';

/** The four designed preview states (AC-22-07). */
describe('SqlPreviewGrid', () => {
  it('renders idle + loading placeholders', () => {
    const { rerender } = render(<SqlPreviewGrid state={{ status: 'idle' }} />);
    expect(screen.getByTestId('sql-preview-idle')).toBeInTheDocument();
    rerender(<SqlPreviewGrid state={{ status: 'loading' }} />);
    expect(screen.getByTestId('sql-preview-loading')).toBeInTheDocument();
  });

  it('renders the sanitized error', () => {
    render(<SqlPreviewGrid state={{ status: 'error', message: "Invalid object name 'Nope'." }} />);
    expect(screen.getByTestId('sql-preview-error')).toHaveTextContent(
      "Invalid object name 'Nope'.",
    );
  });

  it('renders columns with types, rows, and NULL cells', () => {
    render(
      <SqlPreviewGrid
        state={{
          status: 'success',
          preview: {
            columns: [
              { name: 'AccNo', type: 'varchar(12)' },
              { name: 'EmailAddress', type: 'nvarchar(60)' },
              { name: 'Qty', type: 'int' },
            ],
            rows: [
              { AccNo: '3000/A01', EmailAddress: null, Qty: 4 },
              { AccNo: '3000/B02', EmailAddress: 'a@b.my', Qty: 9 },
            ],
            rowCount: 2,
            truncated: false,
            durationMs: 200,
          },
        }}
      />,
    );
    expect(screen.getByTestId('sql-preview-success')).toBeInTheDocument();
    expect(screen.getByText('AccNo')).toBeInTheDocument();
    expect(screen.getByText('varchar(12)')).toBeInTheDocument();
    expect(screen.getByText('3000/A01')).toBeInTheDocument();
    expect(screen.getByText('NULL')).toBeInTheDocument();
    expect(screen.queryByTestId('sql-preview-empty')).not.toBeInTheDocument();
  });

  it('keeps the column header on a 0-row success and states it', () => {
    render(
      <SqlPreviewGrid
        state={{
          status: 'success',
          preview: {
            columns: [{ name: 'Location', type: 'varchar(12)' }],
            rows: [],
            rowCount: 0,
            truncated: false,
            durationMs: 90,
          },
        }}
      />,
    );
    expect(screen.getByText('Location')).toBeInTheDocument();
    expect(screen.getByTestId('sql-preview-empty')).toHaveTextContent('Query returned no rows.');
  });
});
