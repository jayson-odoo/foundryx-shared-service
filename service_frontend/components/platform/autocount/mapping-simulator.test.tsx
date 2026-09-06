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
    // And the parsed mock record is the first - prefilled from the top-level
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

  it('AC-DLA-56 (T7): the field-results grid is a DataGrid, one row per header + line field', async () => {
    const onSimulate = vi.fn().mockResolvedValue({
      ...rejectedResult(),
      lineFields: [
        [
          {
            scope: 'line',
            sourcePath: 'Qty',
            canonicalField: 'quantity',
            present: true,
            ok: true,
            value: 3,
            error: null,
          },
        ],
      ],
    });
    render(<MappingSimulator open onOpenChange={vi.fn()} rows={ROWS} onSimulate={onSimulate} />);
    fireEvent.click(screen.getByRole('button', { name: /run simulation/i }));

    await waitFor(() => expect(screen.getByTestId('field-results')).toBeInTheDocument());
    const grid = screen.getByTestId('field-results');
    expect(grid.querySelector('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Sorento field' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Source' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Value' })).toBeInTheDocument();
    // header field (Code) + header field (Credit limit, failed) + line field (Qty).
    expect(screen.getAllByRole('row')).toHaveLength(4); // 1 header row + 3 data rows.
  });
});

// sprint-5/02 (AC-02-22) - document mode: pick a real header, fetch its lines.
describe('MappingSimulator - document mode (sprint-5/02, AC-02-22)', () => {
  const HEADER_ROWS = [
    { DocKey: '1', DocNo: 'SO-1001', Cancelled: 'F' },
    { DocKey: '2', DocNo: 'SO-1002', Cancelled: 'T' },
  ];

  function documentResult(status: string): AutocountSimulateResult {
    return {
      ok: true,
      sourceRef: 'SO-1001',
      docNo: 'SO-1001',
      record: { so_number: 'SO-1001', status },
      headerFields: [],
      lineFields: [[{ scope: 'line', sourcePath: 'Qty', canonicalField: 'qty_ordered', present: true, ok: true, value: 10, error: null }]],
      status,
      errors: [],
    };
  }

  it('renders a header picker instead of the free-JSON textarea being editable', () => {
    render(
      <MappingSimulator
        open
        onOpenChange={vi.fn()}
        rows={ROWS}
        onSimulate={vi.fn()}
        headerPreviewRows={HEADER_ROWS}
        headerKeyColumns={['DocKey']}
        onFetchLines={vi.fn().mockResolvedValue([])}
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Header row' })).toBeInTheDocument();
    expect(screen.getByLabelText('Mock AutoCount record')).toHaveAttribute('readonly');
  });

  it('picking a header fetches its lines and simulates header + lines together', async () => {
    const onFetchLines = vi.fn().mockResolvedValue([{ DtlKey: 'L1', Qty: 10 }]);
    const onSimulate = vi.fn().mockResolvedValue(documentResult('open'));
    render(
      <MappingSimulator
        open
        onOpenChange={vi.fn()}
        rows={ROWS}
        onSimulate={onSimulate}
        headerPreviewRows={HEADER_ROWS}
        headerKeyColumns={['DocNo']}
        onFetchLines={onFetchLines}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Header row' }));
    fireEvent.click(screen.getByRole('option', { name: 'SO-1001' }));
    // T3 (AC-DLA-20): the header Popover now closes on the shared spring
    // (`AnimatePresence` + `forceMount`, see popover.tsx) instead of a
    // synchronous CSS class toggle - even with `MotionGlobalConfig.
    // skipAnimations` (vitest.setup.ts) collapsing the tween itself, the
    // exit-complete callback that un-hides the rest of the dialog still
    // resolves on a microtask, so a synchronous `fireEvent.click` can query
    // "Run simulation" one tick too early. `waitFor` gives that tick.
    const runButton = await waitFor(() => screen.getByRole('button', { name: /run simulation/i }));
    fireEvent.click(runButton);

    await waitFor(() => expect(onSimulate).toHaveBeenCalled());
    expect(onFetchLines).toHaveBeenCalledWith('SO-1001');
    expect(onSimulate.mock.calls[0][0]).toEqual(HEADER_ROWS[0]);
    expect(onSimulate.mock.calls[0][2]).toEqual([{ DtlKey: 'L1', Qty: 10 }]);
    expect(await screen.findByTestId('simulate-status')).toHaveTextContent('open');
  });

  it('Run simulation is disabled until a header is picked', () => {
    render(
      <MappingSimulator
        open
        onOpenChange={vi.fn()}
        rows={ROWS}
        onSimulate={vi.fn()}
        headerPreviewRows={HEADER_ROWS}
        headerKeyColumns={['DocKey']}
        onFetchLines={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /run simulation/i })).toBeDisabled();
  });
});
