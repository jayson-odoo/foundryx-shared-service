import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AutocountEtlSourceConfig,
  AutocountFormulaTestResult,
  AutocountMappingPreset,
  AutocountSqlConnection,
} from '@/types/autocount';
import type {
  SqlPreviewState,
  UseAutocountSqlSchemaResult,
  UseHttpPreviewResult,
  UseSqlPreviewResult,
} from '@/hooks/use-autocount-etl';
import type { AutocountApiConnection } from '@/types/autocount';
import { SourceTab, type LockedApiConnection, type LockedConnection } from './source-tab';

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

function renderSourceTab(over: {
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
    <SourceTab
      editing
      entityType={over.entityType ?? 'sales_order'}
      sourceKind="db"
      onSourceKindChange={vi.fn()}
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
      apiConnections={[]}
      apiConnectionsLoading={false}
      lockedApiConnection={null}
      httpPreview={{ state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() }}
    />,
  );
  return { onChange, onUsePreset };
}

describe('SourceTab - document line/ref columns (plan 22 S5, AC-22-24)', () => {
  it('shows the line query editor + Test line query button for a document entity', () => {
    renderSourceTab();
    expect(screen.getByTestId('sql-line-editor')).toBeInTheDocument();
    expect(screen.getByTestId('sql-test-line-query')).toBeInTheDocument();
  });

  it('hides the whole document block for a non-document entity', () => {
    renderSourceTab({ entityType: 'customer' });
    expect(screen.queryByTestId('sql-line-editor')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sql-test-line-query')).not.toBeInTheDocument();
  });

  it('runs the line preview with a bound (never real) sample doc key on Test line query', () => {
    const linePreview = idlePreview();
    renderSourceTab({ linePreview });
    fireEvent.click(screen.getByTestId('sql-test-line-query'));
    expect(linePreview.run).toHaveBeenCalledWith(
      'conn-sql-1',
      'SELECT DtlKey, ItemCode FROM SODtl WHERE DocKey = :doc_key',
      { bindDocKey: true, docKey: null },
    );
  });

  it('Test line query is disabled until a line query is present', () => {
    renderSourceTab({ cfg: config({ lineQuery: '' }) });
    expect(screen.getByTestId('sql-test-line-query')).toBeDisabled();
  });

  it('the document date column picker is fed by the HEADER preview, not the line one', () => {
    renderSourceTab({
      preview: successPreview(['DocKey', 'DocNo', 'Status', 'DocDate']),
      linePreview: idlePreview(),
    });
    const picker = screen.getByLabelText('Document date column');
    expect(picker).not.toBeDisabled();
    fireEvent.click(picker);
    expect(screen.getByRole('option', { name: 'DocDate' })).toBeInTheDocument();
  });

  it('a document watermark picker never offers "None" (a document REQUIRES one, S5)', () => {
    renderSourceTab({ preview: successPreview(['DocKey', 'DocNo', 'Status', 'LastModified']) });
    fireEvent.click(screen.getByLabelText('Watermark column'));
    expect(screen.queryByRole('option', { name: 'None' })).not.toBeInTheDocument();
  });

  it('a non-document watermark picker still offers "None"', () => {
    renderSourceTab({
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
describe('SourceTab - Filter formula + presets (sprint-5/02)', () => {
  it('the three line pickers no longer exist', () => {
    renderSourceTab();
    expect(screen.queryByLabelText('Line key column')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Line product column')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Line warehouse column')).not.toBeInTheDocument();
  });

  it('shows "no filter" when unset, and the formula read-only once set', () => {
    renderSourceTab({ cfg: config({ filterFormula: null }) });
    expect(screen.getByText(/no filter/i)).toBeInTheDocument();

    renderSourceTab({ cfg: config({ filterFormula: 'startswith(upper(trim(DocNo)), "SPO-")' }) });
    expect(screen.getByText('startswith(upper(trim(DocNo)), "SPO-")')).toBeInTheDocument();
    // Never a free-text input for it (Q16 - builder-only).
    expect(screen.queryByRole('textbox', { name: /filter/i })).not.toBeInTheDocument();
  });

  it('opens the formula builder to edit the filter, never a bare text field', () => {
    renderSourceTab();
    fireEvent.click(screen.getByRole('button', { name: 'Build the filter formula' }));
    expect(screen.getByLabelText('Formula expression')).toBeInTheDocument();
  });

  it('applying a filter formula patches the config', () => {
    // `DocKey` is the fixture's only known variable (no preview run yet, so
    // the Variables panel offers only the saved key columns) - proves the
    // Apply wiring without needing a full preview run in this test.
    const { onChange } = renderSourceTab();
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
    const { onUsePreset } = renderSourceTab({ presets: [preset] });
    fireEvent.click(screen.getByRole('combobox', { name: 'Use preset' }));
    fireEvent.click(screen.getByRole('option', { name: 'AutoCount SO' }));
    expect(onUsePreset).toHaveBeenCalledWith(preset);
  });

  it('hides "Use preset" entirely when there is none (foolproof-UI)', () => {
    renderSourceTab({ presets: [] });
    expect(screen.queryByRole('combobox', { name: 'Use preset' })).not.toBeInTheDocument();
  });

  it('hides "Use preset" for a non-document entity even with presets passed', () => {
    renderSourceTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null }),
      presets: [],
    });
    expect(screen.queryByRole('combobox', { name: 'Use preset' })).not.toBeInTheDocument();
  });
});

describe('SourceTab - DB company connection lock (plan sprint-5/01, AC-01-19)', () => {
  const LOCKED: LockedConnection = { id: 'conn-sql-1', label: 'AutoCount DB · AED_2024' };

  it('replaces the Connection picker with a read-only row on a DB company', () => {
    renderSourceTab({ entityType: 'customer', cfg: config({ lineQuery: null }), lockedConnection: LOCKED });
    expect(screen.getByTestId('locked-connection')).toHaveTextContent('AutoCount DB · AED_2024');
    expect(screen.queryByRole('combobox', { name: 'Connection' })).not.toBeInTheDocument();
  });

  it('an API company keeps the searchable Connection picker', () => {
    renderSourceTab({ entityType: 'customer', cfg: config({ lineQuery: null }) });
    expect(screen.getByRole('combobox', { name: 'Connection' })).toBeInTheDocument();
    expect(screen.queryByTestId('locked-connection')).not.toBeInTheDocument();
  });

  it('never patches connectionId on mount - the editor seeds it into the baseline (review fix)', () => {
    // A post-mount patch dirtied an untouched editor ("Discard changes?" on
    // Edit -> Cancel); the seed now lives in `TaskEditorView`'s baseline
    // (`task-editor-view.locked-connection.test.tsx`). Pin that the tab itself
    // stays silent even when the config disagrees with the lock.
    const onChange = vi.fn();
    renderSourceTab({
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
    renderSourceTab({
      entityType: 'customer',
      cfg: config({ lineQuery: null }),
      connections: [],
      lockedConnection: LOCKED,
    });
    expect(screen.queryByTestId('no-sql-connection')).not.toBeInTheDocument();
  });

  it('an API company with no SQL connection still gets the warning (regression pin)', () => {
    renderSourceTab({ entityType: 'customer', cfg: config({ lineQuery: null }), connections: [] });
    expect(screen.getByTestId('no-sql-connection')).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// SF3/SF4 (final reviewer pass) - the key-columns MultiSelect / watermark
// SearchSelect withhold each other's chosen column (BL-SS-087's foolproof
// half) by filtering the SHARED OPTIONS list. That's correct for a NORMAL
// save, but a LEGACY config saved before the guard existed can have the
// watermark column sitting INSIDE keyColumns - and today the exclusion
// filters that value out of BOTH pickers' options, which SILENTLY HIDES the
// already-selected value entirely (MultiSelect's pills + SearchSelect's
// trigger label both derive from `options`, not from `value` directly) -
// the operator can't even see what's wrong, let alone fix it by
// deselecting. Only UNSELECTED values should ever be excluded.
// ═══════════════════════════════════════════════════════════════════════════
describe('SourceTab - key/watermark exclusion keeps an already-selected offending column visible (SF3/SF4)', () => {
  function legacyCfg() {
    return config({
      keyColumns: ['DocKey', 'LastModified'],
      watermarkColumn: 'LastModified',
    });
  }

  it('SF3: the key-columns MultiSelect still shows a pill for a legacy watermark-inside-keyColumns value', () => {
    renderSourceTab({
      cfg: legacyCfg(),
      preview: successPreview(['DocKey', 'DocNo', 'Status', 'LastModified']),
    });
    const keyColumnsLabel = screen.getByText(
      (_, el) => el?.tagName === 'LABEL' && (el.textContent ?? '').startsWith('Key columns'),
    );
    const keyColumnsBox = keyColumnsLabel.parentElement as HTMLElement;
    expect(within(keyColumnsBox).getByText('LastModified')).toBeInTheDocument();
  });

  it('SF3: the watermark SearchSelect still shows its selected value, not the "None" placeholder, when that value is also (legacy) a key column', () => {
    renderSourceTab({
      cfg: legacyCfg(),
      preview: successPreview(['DocKey', 'DocNo', 'Status', 'LastModified']),
    });
    const watermarkPicker = screen.getByLabelText('Watermark column');
    expect(watermarkPicker).toHaveTextContent('LastModified');
  });

  it('SF4 (no test today, control): in the NORMAL (non-legacy) state the exclusion still works both ways - a chosen watermark is not offered as a key-column choice, and a chosen key column is not offered as a watermark choice', () => {
    renderSourceTab({
      cfg: config({ keyColumns: ['DocKey'], watermarkColumn: 'LastModified' }),
      preview: successPreview(['DocKey', 'DocNo', 'Status', 'LastModified']),
    });
    // Key-columns popover: LastModified (the watermark) must not be an
    // available option to add.
    const keyColumnsLabel = screen.getByText(
      (_, el) => el?.tagName === 'LABEL' && (el.textContent ?? '').startsWith('Key columns'),
    );
    const keyColumnsBox = keyColumnsLabel.parentElement as HTMLElement;
    fireEvent.click(within(keyColumnsBox).getByRole('combobox'));
    expect(screen.queryByRole('option', { name: 'LastModified' })).not.toBeInTheDocument();

    // Watermark popover: DocKey (the key column) must not be an available
    // option to pick as the watermark.
    fireEvent.click(screen.getByLabelText('Watermark column'));
    expect(screen.queryByRole('option', { name: 'DocKey' })).not.toBeInTheDocument();
  });
});

// ── open REST API source (sprint-5/08, S1 - AC-08-18/19/20) ──────────────────

function httpConfig(over: Partial<AutocountEtlSourceConfig> = {}): AutocountEtlSourceConfig {
  return config({
    lineQuery: null,
    keyColumns: [],
    connectionId: 'conn-api-sorento',
    path: '/itembypage',
    keyFields: ['ItemCode'],
    watermarkField: 'LastModified',
    comparedFields: [],
    ...over,
  });
}

function idleHttpPreview(): UseHttpPreviewResult {
  return { state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() };
}

function successHttpPreview(): UseHttpPreviewResult {
  return {
    state: {
      status: 'success',
      preview: {
        envelope: 'paged',
        totalCount: 11826,
        columns: [
          { name: 'ItemCode', sample: 'SRT-01' },
          { name: 'LastModified', sample: '2026-08-01T00:00:00' },
        ],
        rows: [],
        durationMs: 220,
      },
    },
    run: vi.fn(),
    fieldErrors: {},
    reset: vi.fn(),
  };
}

const API_CONNECTIONS: AutocountApiConnection[] = [
  { id: 'conn-api-sorento', name: 'Sorento REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db1', auth: 'none' },
  { id: 'conn-api-vendor', name: 'AutoCount Vendor API', baseUrl: 'https://api.autocountcloud.com', auth: 'basic' },
];

function renderApiBranch(over: {
  entityType?: string;
  cfg?: AutocountEtlSourceConfig;
  httpPreview?: UseHttpPreviewResult;
  onChange?: (patch: Partial<AutocountEtlSourceConfig>) => void;
  onSourceKindChange?: (kind: 'db' | 'api') => void;
  apiConnections?: AutocountApiConnection[];
  lockedApiConnection?: LockedApiConnection | null;
  fieldErrors?: Record<string, string>;
} = {}) {
  const onChange = over.onChange ?? vi.fn();
  const onSourceKindChange = over.onSourceKindChange ?? vi.fn();
  render(
    <SourceTab
      editing
      entityType={over.entityType ?? 'product'}
      sourceKind="api"
      onSourceKindChange={onSourceKindChange}
      config={over.cfg ?? httpConfig()}
      onChange={onChange}
      connections={[]}
      connectionsLoading={false}
      lockedConnection={null}
      schema={EMPTY_SCHEMA}
      preview={idlePreview()}
      linePreview={idlePreview()}
      fieldErrors={over.fieldErrors ?? {}}
      onServerTest={passThroughServer}
      apiConnections={over.apiConnections ?? API_CONNECTIONS}
      apiConnectionsLoading={false}
      lockedApiConnection={over.lockedApiConnection ?? null}
      httpPreview={over.httpPreview ?? idleHttpPreview()}
    />,
  );
  return { onChange, onSourceKindChange };
}

describe('SourceTab - Source toggle (sprint-5/08 D13, AC-08-19)', () => {
  it('renders API | Database segments', () => {
    renderApiBranch();
    expect(screen.getByRole('radio', { name: 'API' })).toHaveAttribute('data-state', 'on');
    expect(screen.getByRole('radio', { name: 'Database' })).toHaveAttribute('data-state', 'off');
  });

  it('toggling to Database calls onSourceKindChange', () => {
    const { onSourceKindChange } = renderApiBranch();
    fireEvent.click(screen.getByRole('radio', { name: 'Database' }));
    expect(onSourceKindChange).toHaveBeenCalledWith('db');
  });
});

describe('SourceTab - API branch, free picker (AC-08-19)', () => {
  it('lists every autocount connection, badged by auth (an API-capable entity sees both auths)', () => {
    renderApiBranch({ entityType: 'customer', cfg: httpConfig({ connectionId: null }) });
    fireEvent.click(screen.getByRole('combobox', { name: 'Connection' }));
    expect(screen.getByRole('option', { name: 'Sorento REST (No auth)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'AutoCount Vendor API (Basic auth)' })).toBeInTheDocument();
  });

  it('picking a connection resets the preview and calls onChange', () => {
    const httpPreview = idleHttpPreview();
    const { onChange } = renderApiBranch({ cfg: httpConfig({ connectionId: null }), httpPreview });
    fireEvent.click(screen.getByRole('combobox', { name: 'Connection' }));
    fireEvent.click(screen.getByRole('option', { name: 'Sorento REST (No auth)' }));
    expect(onChange).toHaveBeenCalledWith({ connectionId: 'conn-api-sorento' });
    expect(httpPreview.reset).toHaveBeenCalled();
  });
});

describe('SourceTab - API branch, locked connection (AC-08-19)', () => {
  it('shows a read-only locked row with the auth badge, no picker', () => {
    renderApiBranch({
      lockedApiConnection: { id: 'conn-api-sorento', label: 'Sorento REST', auth: 'none' },
    });
    expect(screen.getByTestId('locked-api-connection')).toHaveTextContent('Sorento REST');
    expect(screen.getByTestId('locked-api-connection')).toHaveTextContent('No auth');
    expect(screen.queryByRole('combobox', { name: 'Connection' })).not.toBeInTheDocument();
  });
});

describe('SourceTab - API branch, path + Test + preview (AC-08-14/19)', () => {
  it('the path input is editable and preset-filled', () => {
    renderApiBranch();
    expect(screen.getByLabelText('Endpoint path')).toHaveValue('/itembypage');
  });

  it('Test is disabled until connectionId + path are set', () => {
    renderApiBranch({ cfg: httpConfig({ connectionId: null }) });
    expect(screen.getByTestId('http-test-path')).toBeDisabled();
  });

  it('Test runs the http preview with connectionId/path/distinctOf', () => {
    const httpPreview = idleHttpPreview();
    renderApiBranch({ httpPreview, cfg: httpConfig({ distinctOf: ['BaseUOM'] }) });
    fireEvent.click(screen.getByTestId('http-test-path'));
    expect(httpPreview.run).toHaveBeenCalledWith('conn-api-sorento', '/itembypage', ['BaseUOM']);
  });

  it('shows the envelope badge (D14 - a run walks every page)', () => {
    renderApiBranch({ httpPreview: successHttpPreview() });
    expect(screen.getByTestId('http-preview-badge')).toHaveTextContent(
      'Paged · 11,826 total · 12 pages of 1000 - a run walks every page',
    );
  });

  it('reuses SqlPreviewGrid for the results (AC-08-19 - never a parallel grid)', () => {
    renderApiBranch({ httpPreview: successHttpPreview() });
    const grid = screen.getByTestId('sql-preview-success');
    expect(grid).toBeInTheDocument();
    expect(within(grid).getByText('ItemCode')).toBeInTheDocument();
  });

  it('shows the "derived from distinct values of" chips when distinctOf is set', () => {
    renderApiBranch({ cfg: httpConfig({ distinctOf: ['BaseUOM', 'SalesUOM'] }) });
    expect(screen.getByText('BaseUOM')).toBeInTheDocument();
    expect(screen.getByText('SalesUOM')).toBeInTheDocument();
  });

  it('surfaces a 422 on the path field inline', () => {
    renderApiBranch({ fieldErrors: { path: "'/bogus' was not found." } });
    expect(screen.getByText("'/bogus' was not found.")).toBeInTheDocument();
  });

  it('feeds the key/watermark/compared pickers from the preview columns', () => {
    renderApiBranch({ httpPreview: successHttpPreview() });
    fireEvent.click(screen.getByLabelText('Watermark column'));
    expect(screen.getByRole('option', { name: 'LastModified' })).toBeInTheDocument();
  });
});

describe('SourceTab - API branch, no connection (AC-08-20)', () => {
  it('warns and links to Settings -> Integrations when there is nothing to pick', () => {
    renderApiBranch({ apiConnections: [] });
    expect(screen.getByTestId('no-api-connection')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings -> Integrations' })).toHaveAttribute(
      'href',
      '/settings/integrations/new',
    );
  });
});

describe('SourceTab - API branch, basic-auth connection (D13 - no endpoint to configure)', () => {
  it('a GRN/supplier/customer entity on a basic-auth connection shows the read-only message, no path/Test/pickers', () => {
    renderApiBranch({
      entityType: 'customer',
      cfg: httpConfig({ connectionId: 'conn-api-vendor' }),
    });
    expect(screen.getByTestId('basic-auth-source')).toBeInTheDocument();
    expect(screen.queryByLabelText('Endpoint path')).not.toBeInTheDocument();
    expect(screen.queryByTestId('http-test-path')).not.toBeInTheDocument();
  });

  it('a non-capable entity never offers a basic-auth connection in the free picker (foolproof-UI)', () => {
    renderApiBranch({ entityType: 'product', cfg: httpConfig({ connectionId: null }) });
    fireEvent.click(screen.getByRole('combobox', { name: 'Connection' }));
    expect(screen.queryByRole('option', { name: 'AutoCount Vendor API (Basic auth)' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Sorento REST (No auth)' })).toBeInTheDocument();
  });
});
