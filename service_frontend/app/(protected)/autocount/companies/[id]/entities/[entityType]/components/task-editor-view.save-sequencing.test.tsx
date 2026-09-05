import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountEtlTask, AutocountMappingView } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';

/**
 * SF1 (final reviewer pass) - `onSave` unconditionally calls `mapping.reload()`
 * whenever the query config was dirty, REGARDLESS of whether the mapping
 * draft was ALSO dirty. When both are dirty, `mapping.save(rows, lineRows)`
 * runs right after and already sets the fresh view itself (see
 * `useAutocountMapping.save` - `setView(next)`) - the extra `reload()` fires
 * a second, redundant, RACY refetch that can resolve in either order against
 * the save's own state update. Contract: `reload()` fires ONLY when the
 * config was the ONLY dirty side (a clean mapping draft needs the explicit
 * refetch - S2's original reason for calling it at all, the
 * "seed_document_mapping on first save" case).
 *
 * Real `ResourceForm` + real tab navigation, hooks mocked at the boundary
 * (matches `task-editor-view.locked-connection.test.tsx`'s pattern) - the
 * point under test is the SEQUENCING inside `onSave`, not tab routing.
 */

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'Asia/Kuala_Lumpur',
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

function baseTask(): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Debtor',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo', 'CompanyName'],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

function mappingView(): AutocountMappingView {
  return {
    entityType: 'customer',
    rows: [
      {
        sourcePath: 'AccNo', transform: 'string', formula: null,
        sorentoField: 'code', canonicalField: 'code', scope: 'header',
        isRequired: true, isEnabled: true,
      },
    ],
    // A SECOND, still-unmapped target so "Add field" is enabled
    // (`allTargetsUsed` false).
    sorentoFields: [
      { field: 'code', required: true },
      { field: 'name', required: false },
    ],
    acFields: ['AccNo', 'CompanyName'],
    lineSorentoFields: [],
    lineAcFields: [],
  };
}

const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const etlSaveSpy = vi.hoisted(() => vi.fn().mockResolvedValue(true));

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({ detail: null, isLoading: false, notFound: false, reload: vi.fn() }),
}));

vi.mock('@/hooks/use-autocount-etl', () => ({
  useLineFetcher: () => ({ fetchLines: vi.fn().mockResolvedValue([]) }),
  useAutocountEtlTask: () => ({
    task: taskBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    fieldErrors: {},
    isSaving: false,
    save: etlSaveSpy,
    apply: vi.fn(),
    reload: vi.fn(),
  }),
  useAutocountSqlConnections: () => ({
    connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'postgresql', database: 'AED_2024' }],
    isLoading: false,
    error: null,
  }),
  useAutocountSqlSchema: () => ({ schema: null, isLoading: false, error: null, refresh: vi.fn() }),
  useEtlTaskLifecycle: () => ({
    busy: null, error: null, activate: vi.fn(), pause: vi.fn(), resume: vi.fn(), runNow: vi.fn(),
    clearError: vi.fn(),
  }),
  useEtlTaskPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  useSqlPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
}));

const mappingSaveSpy = vi.hoisted(() => vi.fn().mockResolvedValue(true));
const mappingReloadSpy = vi.hoisted(() => vi.fn());
const mappingViewBox = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: mappingViewBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: mappingSaveSpy,
    reload: mappingReloadSpy,
    testFormula: vi.fn(),
    simulate: vi.fn(),
  }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function saveButton() {
  return screen.getByRole('button', { name: 'Save' });
}

beforeEach(() => {
  etlSaveSpy.mockClear();
  mappingSaveSpy.mockClear();
  mappingReloadSpy.mockClear();
  taskBox.current = baseTask();
  mappingViewBox.current = mappingView();
});

describe('TaskEditorView.onSave - reload race (SF1, final reviewer pass)', () => {
  it('does NOT call mapping.reload() when BOTH the config and the mapping draft are dirty - mapping.save() already returns the fresh view', async () => {
    const user = userEvent.setup();
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    fireEvent.click(editButton());

    // Dirty the QUERY CONFIG side via the Schedule tab's plain number input.
    await user.click(screen.getByRole('tab', { name: 'Schedule' }));
    fireEvent.change(screen.getByTestId('etl-incremental-minutes'), { target: { value: '30' } });

    // Dirty the MAPPING DRAFT side via the Mapping tab's "Add field".
    await user.click(screen.getByRole('tab', { name: 'Mapping' }));
    fireEvent.click(screen.getByRole('button', { name: /Add field/i }));
    // The new row starts with a BLANK source column (foolproof-UI: `validate()`
    // rejects a save with any blank source), so pick one to make the row a
    // genuine, savable edit.
    await user.click(screen.getByLabelText('Source column for row 2'));
    await user.click(screen.getByRole('option', { name: 'CompanyName' }));

    await user.click(saveButton());

    expect(etlSaveSpy).toHaveBeenCalled();
    expect(mappingSaveSpy).toHaveBeenCalled();
    expect(mappingReloadSpy).not.toHaveBeenCalled();
  });

  it('DOES call mapping.reload() when only the config is dirty and the mapping draft is clean', async () => {
    const user = userEvent.setup();
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    fireEvent.click(editButton());

    await user.click(screen.getByRole('tab', { name: 'Schedule' }));
    fireEvent.change(screen.getByTestId('etl-incremental-minutes'), { target: { value: '30' } });
    // Mapping tab is never touched - the draft stays clean.

    await user.click(saveButton());

    expect(etlSaveSpy).toHaveBeenCalled();
    expect(mappingSaveSpy).not.toHaveBeenCalled();
    expect(mappingReloadSpy).toHaveBeenCalledTimes(1);
  });
});
