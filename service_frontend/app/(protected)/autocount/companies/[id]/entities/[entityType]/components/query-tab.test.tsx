import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AutocountEtlSourceConfig,
  AutocountFormulaTestResult,
  AutocountMappingPreset,
  AutocountSqlConnection,
} from '@/types/autocount';
import type { SqlPreviewState, UseAutocountSqlSchemaResult, UseSqlPreviewResult } from '@/hooks/use-autocount-etl';
import { QueryTab, type LockedConnection } from './query-tab';

/**
 * Query tab - plan 22 S5 additions (AC-22-24): the line-query test leg,
 * gated on the LINE preview (never the header one) and hidden entirely for a
 * non-document entity (foolproof-UI: no dead controls). Sprint-5/02
 * (AC-02-19/20): the line key/product/warehouse pickers are GONE (they moved
 * to persisted line mapping rows) - the document block instead carries a
 * Filter formula field (builder-only, no free text) and "Use preset".
 */

function config(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return {
    connectionId: 'conn-sql-1',
    query: 'SELECT DocKey, DocNo, Status FROM SO',
    lineQuery: 'SELECT DtlKey, ItemCode FROM SODtl WHERE DocKey = :doc_key',
    keyColumns: ['DocKey'],
    watermarkColumn: null,
    comparedColumns: [],
    fromDate: '2026-08-30',
    docDateColumn: null,
    filterFormula: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
}

function passThroughServer(formula: string, value: unknown): Promise<AutocountFormulaTestResult> {
  return Promise.resolve({ ok: true, output: value, error: null });
}

const CONNECTIONS: AutocountSqlConnection[] = [
  { id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'mssql', database: 'AED_2024' },
];

function idlePreview(): UseSqlPreviewResult {
  return { state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() };
}

function successPreview(columns: string[]): UseSqlPreviewResult {
  const state: SqlPreviewState = {
    status: 'success',
    preview: {
      columns: columns.map((name) => ({ name, type: 'string' })),
      rows: [],
      rowCount: 0,
      truncated: false,
      durationMs: 12,
    },
  };
  return { state, run: vi.fn(), reset: vi.fn() };
}

const EMPTY_SCHEMA: UseAutocountSqlSchemaResult = {
  schema: null,
  isLoading: false,
  error: null,
  refresh: vi.fn(),
};

function renderQueryTab(over: {
  entityType?: string;
  cfg?: AutocountEtlSourceConfig;
  preview?: UseSqlPreviewResult;
  linePreview?: UseSqlPreviewResult;
  onChange?: (patch: Partial<AutocountEtlSourceConfig>) => void;
  connections?: AutocountSqlConnection[];
  lockedConnection?: LockedConnection | null;
  presets?: AutocountMappingPreset[];
  onUsePreset?: (preset: AutocountMappingPreset) => void;
} = {}) {
  const onChange = over.onChange ?? vi.fn();
  const onUsePreset = over.onUsePreset ?? vi.fn();
  render(
    <QueryTab
      editing
      entityType={over.entityType ?? 'sales_order'}
      config={over.cfg ?? config()}
      onChange={onChange}
      connections={over.connections ?? CONNECTIONS}
      connectionsLoading={false}
      lockedConnection={over.lockedConnection ?? null}
      schema={EMPTY_SCHEMA}
      preview={over.preview ?? idlePreview()}
      linePreview={over.linePreview ?? idlePreview()}
      fieldErrors={{}}
      presets={over.presets}
      onUsePreset={onUsePreset}
      onServerTest={passThroughServer}
    />,
  );
  return { onChange, onUsePreset };
}

describe('QueryTab - document line/ref columns (plan 22 S5, AC-22-24)', () => {
  it('shows the line query editor + Test line query button for a document entity', () => {
    renderQueryTab();
    expect(screen.getByTestId('sql-line-editor')).toBeInTheDocument();
    expect(screen.getByTestId('sql-test-line-query')).toBeInTheDocument();
  });

  it('hides the whole document block for a non-document entity', () => {
    renderQueryTab({ entityType: 'customer' });
    expect(screen.queryByTestId('sql-line-editor')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sql-test-line-query')).not.toBeInTheDocument();
  });

  it('runs the line preview with a bound (never real) sample doc key on Test line query', () => {
    const linePreview = idlePreview();
    renderQueryTab({ linePreview });
    fireEvent.click(screen.getByTestId('sql-test-line-query'));
    expect(linePreview.run).toHaveBeenCalledWith(
      'conn-sql-1',
      'SELECT DtlKey, ItemCode FROM SODtl WHERE DocKey = :doc_key',
      { bindDocKey: true, docKey: null },
    );
  });

  it('Test line query is disabled until a line query is present', () => {
    renderQueryTab({ cfg: config({ lineQuery: '' }) });
    expect(screen.getByTestId('sql-test-line-query')).toBeDisabled();
  });

  it('the document date column picker is fed by the HEADER preview, not the line one', () => {
    renderQueryTab({
      preview: successPreview(['DocKey', 'DocNo', 'Status', 'DocDate']),
      linePreview: idlePreview(),
    });
    const picker = screen.getByLabelText('Document date column');
    expect(picker).not.toBeDisabled();
    fireEvent.click(picker);
    expect(screen.getByRole('option', { name: 'DocDate' })).toBeInTheDocument();
  });

  it('a document watermark picker never offers "None" (a document REQUIRES one, S5)', () => {
    renderQueryTab({ preview: successPreview(['DocKey', 'DocNo', 'Status', 'LastModified']) });
    fireEvent.click(screen.getByLabelText('Watermark column'));
    expect(screen.queryByRole('option', { name: 'None' })).not.toBeInTheDocument();
  });

  it('a non-document watermark picker still offers "None"', () => {
    renderQueryTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null, keyColumns: ['AccNo'] }),
      preview: successPreview(['AccNo', 'CompanyName', 'LastModified']),
    });
    fireEvent.click(screen.getByLabelText('Watermark column'));
    expect(screen.getByRole('option', { name: 'None' })).toBeInTheDocument();
  });

});

// sprint-5/02 (AC-02-19/20) - the line pickers are gone; a Filter formula
// field (builder-only) + "Use preset" take their place.
describe('QueryTab - Filter formula + presets (sprint-5/02)', () => {
  it('the three line pickers no longer exist', () => {
    renderQueryTab();
    expect(screen.queryByLabelText('Line key column')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Line product column')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Line warehouse column')).not.toBeInTheDocument();
  });

  it('shows "no filter" when unset, and the formula read-only once set', () => {
    renderQueryTab({ cfg: config({ filterFormula: null }) });
    expect(screen.getByText(/no filter/i)).toBeInTheDocument();

    renderQueryTab({ cfg: config({ filterFormula: 'startswith(upper(trim(DocNo)), "SPO-")' }) });
    expect(screen.getByText('startswith(upper(trim(DocNo)), "SPO-")')).toBeInTheDocument();
    // Never a free-text input for it (Q16 - builder-only).
    expect(screen.queryByRole('textbox', { name: /filter/i })).not.toBeInTheDocument();
  });

  it('opens the formula builder to edit the filter, never a bare text field', () => {
    renderQueryTab();
    fireEvent.click(screen.getByRole('button', { name: 'Build the filter formula' }));
    expect(screen.getByLabelText('Formula expression')).toBeInTheDocument();
  });

  it('applying a filter formula patches the config', () => {
    // `DocKey` is the fixture's only known variable (no preview run yet, so
    // the Variables panel offers only the saved key columns) - proves the
    // Apply wiring without needing a full preview run in this test.
    const { onChange } = renderQueryTab();
    fireEvent.click(screen.getByRole('button', { name: 'Build the filter formula' }));
    fireEvent.change(screen.getByLabelText('Formula expression'), {
      target: { value: 'startswith(upper(trim(DocKey)), "SPO-")' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onChange).toHaveBeenCalledWith({ filterFormula: 'startswith(upper(trim(DocKey)), "SPO-")' });
  });

  it('offers "Use preset" only when presets exist, and inserts on pick', () => {
    const preset: AutocountMappingPreset = {
      entityType: 'sales_order',
      label: 'AutoCount SO',
      headerQuery: 'SELECT DocKey, DocNo FROM AED.dbo.SO_Header',
      lineQuery: 'SELECT DtlKey FROM AED.dbo.SO_Dtl WHERE DocKey = :doc_key',
      keyColumns: ['DocKey'],
      watermarkColumn: 'LastModified',
      docDateColumn: 'DocDate',
      fromDate: '2026-01-01',
      filterFormula: null,
    };
    const { onUsePreset } = renderQueryTab({ presets: [preset] });
    fireEvent.click(screen.getByRole('combobox', { name: 'Use preset' }));
    fireEvent.click(screen.getByRole('option', { name: 'AutoCount SO' }));
    expect(onUsePreset).toHaveBeenCalledWith(preset);
  });

  it('hides "Use preset" entirely when there is none (foolproof-UI)', () => {
    renderQueryTab({ presets: [] });
    expect(screen.queryByRole('combobox', { name: 'Use preset' })).not.toBeInTheDocument();
  });

  it('hides "Use preset" for a non-document entity even with presets passed', () => {
    renderQueryTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null }),
      presets: [],
    });
    expect(screen.queryByRole('combobox', { name: 'Use preset' })).not.toBeInTheDocument();
  });
});

describe('QueryTab - DB company connection lock (plan sprint-5/01, AC-01-19)', () => {
  const LOCKED: LockedConnection = { id: 'conn-sql-1', label: 'AutoCount DB · AED_2024' };

  it('replaces the Connection picker with a read-only row on a DB company', () => {
    renderQueryTab({ entityType: 'customer', cfg: config({ lineQuery: null }), lockedConnection: LOCKED });
    expect(screen.getByTestId('locked-connection')).toHaveTextContent('AutoCount DB · AED_2024');
    expect(screen.queryByRole('combobox', { name: 'Connection' })).not.toBeInTheDocument();
  });

  it('an API company keeps the searchable Connection picker', () => {
    renderQueryTab({ entityType: 'customer', cfg: config({ lineQuery: null }) });
    expect(screen.getByRole('combobox', { name: 'Connection' })).toBeInTheDocument();
    expect(screen.queryByTestId('locked-connection')).not.toBeInTheDocument();
  });

  it('never patches connectionId on mount - the editor seeds it into the baseline (review fix)', () => {
    // A post-mount patch dirtied an untouched editor ("Discard changes?" on
    // Edit -> Cancel); the seed now lives in `TaskEditorView`'s baseline
    // (`task-editor-view.locked-connection.test.tsx`). Pin that the tab itself
    // stays silent even when the config disagrees with the lock.
    const onChange = vi.fn();
    renderQueryTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null, connectionId: 'conn-other' }),
      lockedConnection: LOCKED,
      onChange,
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('never shows the "No SQL database connection yet." warning on a DB company', () => {
    // Even with an empty connection list (still loading elsewhere / not visible):
    // the company connection IS the connection.
    renderQueryTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null }),
      connections: [],
      lockedConnection: LOCKED,
    });
    expect(screen.queryByTestId('no-sql-connection')).not.toBeInTheDocument();
  });

  it('an API company with no SQL connection still gets the warning (regression pin)', () => {
    renderQueryTab({ entityType: 'customer', cfg: config({ lineQuery: null }), connections: [] });
    expect(screen.getByTestId('no-sql-connection')).toBeInTheDocument();
  });
});
