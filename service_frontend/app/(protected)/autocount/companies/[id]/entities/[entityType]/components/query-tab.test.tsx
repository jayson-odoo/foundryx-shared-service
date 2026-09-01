import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEtlSourceConfig, AutocountSqlConnection } from '@/types/autocount';
import type { SqlPreviewState, UseAutocountSqlSchemaResult, UseSqlPreviewResult } from '@/hooks/use-autocount-etl';
import { QueryTab } from './query-tab';

/**
 * Query tab - plan 22 S5 additions (AC-22-24): the line-query test leg +
 * the docDateColumn/lineKeyColumn/lineProductColumn/lineWarehouseColumn
 * pickers, all gated on the LINE preview (never the header one) and hidden
 * entirely for a non-document entity (foolproof-UI: no dead controls).
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
    lineKeyColumn: null,
    lineProductColumn: null,
    lineWarehouseColumn: null,
    incrementalMinutes: 15,
    reconcileMode: 'dailyAt',
    reconcileHours: null,
    reconcileAt: '02:00',
    ...over,
  };
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
} = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <QueryTab
      editing
      entityType={over.entityType ?? 'sales_order'}
      config={over.cfg ?? config()}
      onChange={onChange}
      connections={CONNECTIONS}
      connectionsLoading={false}
      schema={EMPTY_SCHEMA}
      preview={over.preview ?? idlePreview()}
      linePreview={over.linePreview ?? idlePreview()}
      fieldErrors={{}}
    />,
  );
  return { onChange };
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

  it('line-column pickers are disabled until the line query has been tested', () => {
    renderQueryTab({ linePreview: idlePreview() });
    expect(screen.getByLabelText('Line key column')).toBeDisabled();
    expect(screen.getByLabelText('Line product column')).toBeDisabled();
    expect(screen.getByLabelText('Line warehouse column')).toBeDisabled();
  });

  it('line-column pickers enable and offer the LINE preview columns once tested', () => {
    renderQueryTab({ linePreview: successPreview(['DtlKey', 'ItemCode', 'Location']) });
    const keyPicker = screen.getByLabelText('Line key column');
    expect(keyPicker).not.toBeDisabled();
    fireEvent.click(keyPicker);
    expect(screen.getByRole('option', { name: 'DtlKey' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ItemCode' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Location' })).toBeInTheDocument();
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

  it('picking a line key/product column patches the config', () => {
    const { onChange } = renderQueryTab({
      linePreview: successPreview(['DtlKey', 'ItemCode']),
    });
    fireEvent.click(screen.getByLabelText('Line key column'));
    fireEvent.click(screen.getByRole('option', { name: 'DtlKey' }));
    expect(onChange).toHaveBeenCalledWith({ lineKeyColumn: 'DtlKey' });
  });
});
