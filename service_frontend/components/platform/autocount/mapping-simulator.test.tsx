import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AutocountMappingWriteRow,
  AutocountSimulateResult,
} from '@/types/autocount';
import { MappingSimulator } from './mapping-simulator';

const ROWS: AutocountMappingWriteRow[] = [
  { sourcePath: 'AccNo', transform: 'string', formula: null, sorentoField: 'code' },
  { sourcePath: 'CreditLimit', transform: 'decimal', formula: 'number(value)', sorentoField: 'credit_limit' },
];

function rejectedResult(): AutocountSimulateResult {
  return {
    ok: false,
    sourceRef: 'A1',
    docNo: null,
    record: null,
    headerFields: [
      {
        scope: 'header',
        sourcePath: 'AccNo',
        canonicalField: 'code',
        present: true,
        ok: true,
        value: 'A1',
        error: null,
      },
      {
        scope: 'header',
        sourcePath: 'CreditLimit',
        canonicalField: 'credit_limit',
        present: true,
        ok: false,
        value: null,
        error: 'number() expected a number, got "abc".',
      },
    ],
    lineFields: [],
    errors: [{ field: 'credit_limit', message: 'number() expected a number, got "abc".' }],
  };
}

describe('MappingSimulator (AC-16-30/31)', () => {
  it('runs the mapping and shows record-in → record-out with per-field errors', async () => {
    const onSimulate = vi.fn().mockResolvedValue(rejectedResult());
    render(
      <MappingSimulator
        open
        onOpenChange={vi.fn()}
        rows={ROWS}
        onSimulate={onSimulate}
        entityLabel="Supplier"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /run simulation/i }));

    // Per-field results render, including the failing field's error.
    await waitFor(() => expect(screen.getByTestId('field-results')).toBeInTheDocument());
    expect(screen.getByText('number() expected a number, got "abc".')).toBeInTheDocument();
    // A rejected record is shown as such, never silently blank.
    expect(screen.getByTestId('sorento-output')).toHaveTextContent(/would be rejected/i);
  });

  it('sends the CURRENT draft rows so unsaved edits preview (AC-16-30)', async () => {
    const onSimulate = vi.fn().mockResolvedValue({
      ...rejectedResult(),
      ok: true,
      record: { code: 'A1' },
      headerFields: [
        {
          scope: 'header',
          sourcePath: 'AccNo',
          canonicalField: 'code',
          present: true,
          ok: true,
          value: 'A1',
          error: null,
        },
      ],
    });
    render(<MappingSimulator open onOpenChange={vi.fn()} rows={ROWS} onSimulate={onSimulate} />);
    fireEvent.click(screen.getByRole('button', { name: /run simulation/i }));
    await waitFor(() => expect(onSimulate).toHaveBeenCalled());
    // The draft rows are the second argument.
    expect(onSimulate.mock.calls[0][1]).toEqual(ROWS);
    // And the parsed mock record is the first — prefilled from the top-level
    // (non-dotted) source paths of the current rows.
    expect(onSimulate.mock.calls[0][0]).toEqual({ AccNo: '', CreditLimit: '' });
  });

  it('rejects invalid JSON before running', () => {
    const onSimulate = vi.fn();
    render(<MappingSimulator open onOpenChange={vi.fn()} rows={ROWS} onSimulate={onSimulate} />);
    fireEvent.change(screen.getByLabelText('Mock AutoCount record'), {
      target: { value: '{ not json' },
    });
    expect(screen.getByTestId('record-parse-error')).toHaveTextContent(/not valid json/i);
    fireEvent.click(screen.getByRole('button', { name: /run simulation/i }));
    expect(onSimulate).not.toHaveBeenCalled();
  });
});
