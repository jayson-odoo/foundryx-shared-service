import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RecordDiff } from './record-diff';

describe('RecordDiff (AC-13-12)', () => {
  it('shows before → after for each changed field', () => {
    render(
      <RecordDiff
        diff={{
          total: { from: '100.00', to: '120.00' },
          supplier_name: { from: 'Acme', to: 'Acme Sdn Bhd' },
        }}
      />,
    );
    expect(screen.getByText('Total')).toBeInTheDocument();
    expect(screen.getByText('100.00')).toBeInTheDocument();
    expect(screen.getByText('120.00')).toBeInTheDocument();
    expect(screen.getByText('Supplier name')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('Acme Sdn Bhd')).toBeInTheDocument();
  });

  it('does NOT render unchanged fields as changes', () => {
    render(
      <RecordDiff
        diff={{ total: { from: '100.00', to: '120.00' } }}
        canonical={{ total: '120.00', supplier_name: 'Acme', doc_no: 'GRN-001' }}
      />,
    );
    expect(screen.getByTestId('diff-row-total')).toBeInTheDocument();
    expect(screen.queryByTestId('diff-row-supplier_name')).not.toBeInTheDocument();
    expect(screen.queryByTestId('diff-row-doc_no')).not.toBeInTheDocument();
    expect(screen.queryByText('Acme')).not.toBeInTheDocument();
  });

  it('renders sensibly for a record with no changes', () => {
    render(<RecordDiff diff={{}} />);
    expect(screen.getByTestId('diff-no-changes')).toHaveTextContent('No field changes.');
    expect(screen.queryByTestId('record-diff')).not.toBeInTheDocument();
  });

  it('renders sensibly for a record with a null diff', () => {
    render(<RecordDiff diff={null} />);
    expect(screen.getByTestId('diff-no-changes')).toBeInTheDocument();
  });

  it('expands a first-seen record as nothing → value', () => {
    render(
      <RecordDiff
        diff={{ __new__: true }}
        canonical={{ doc_no: 'GRN-001', cancelled: false }}
      />,
    );
    expect(screen.getByTestId('diff-row-doc_no')).toBeInTheDocument();
    expect(screen.getByText('GRN-001')).toBeInTheDocument();
    // `false` is a real value, not emptiness.
    expect(screen.getByTestId('diff-row-cancelled')).toHaveTextContent('No');
  });

  it('never surfaces last_modified as a change on the new-record path', () => {
    render(
      <RecordDiff
        diff={{ __new__: true }}
        canonical={{ doc_no: 'GRN-001', last_modified: '2026-07-01T00:00:00Z' }}
      />,
    );
    expect(screen.queryByTestId('diff-row-last_modified')).not.toBeInTheDocument();
  });

  it('puts a structured value in its own scrollable block, not inline text', () => {
    const { container } = render(
      <RecordDiff diff={{ lines: { from: [], to: [{ itemCode: 'A1', qty: 2 }] } }} />,
    );
    const pres = container.querySelectorAll('pre');
    // Only the "after" side is structured - an empty "before" collection reads
    // as nothing rather than a bare `[]` block.
    expect(pres).toHaveLength(1);
    expect(pres[0].className).toContain('overflow-auto');
    expect(pres[0].textContent).toContain('itemCode');
  });

  it('shows an em dash where a side is genuinely empty', () => {
    render(<RecordDiff diff={{ description: { from: null, to: 'Urgent' } }} />);
    const row = screen.getByTestId('diff-row-description');
    expect(row).toHaveTextContent('-');
    expect(row).toHaveTextContent('Urgent');
  });
});
