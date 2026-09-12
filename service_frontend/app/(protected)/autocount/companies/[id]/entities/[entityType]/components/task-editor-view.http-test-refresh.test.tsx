import { act, fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/08 review round 7 - B1: round 6's fix called `reload()` inside
 * `onHttpPreviewSuccess`, which re-triggered the `[task]`-keyed seed effect
 * with the SAVED connectionId/path pair, overwriting the just-tested
 * (possibly UNSAVED) pair `onHttpPreviewSuccess` had just set. Save would go
 * from enabled back to disabled with no explanation, and a changed
 * endpoint/connection could never be saved.
 *
 * The fix: the backend's `preview_http` echoes the task AFTER stamping as an
 * additive `HttpPreview.task` (round 7); `onHttpPreviewSuccess` `apply()`s it
 * directly (no second GET to race a concurrent Save), and the seed effect
 * only seeds `httpPreviewedFor` ONCE (`prev ?? seeded`) rather than on every
 * `task` change.
 *
 * Unlike the round-6 version of this file, `useAutocountEtlTask` and
 * `useHttpPreview` are the REAL hooks here (mocked at the SERVICE layer) -
 * a fully-mocked hook could not have caught B1, since the bug lived in how
 * the real seed effect reacted to a real `apply()`.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

// The Review & Activate tab (`ActivateTab`) reads `useDatetime()` ->
// `useSession()` - unrelated to this suite's Test/apply() seam, stubbed the
// same way `app/(protected)/settings/general/page.test.tsx` does.
vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { id: 'u1', timezone: 'UTC' } } }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const getEtlTask = vi.fn();
const updateEtlTask = vi.fn();
const previewHttp = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getEtlTask: (...args: unknown[]) => getEtlTask(...args),
    updateEtlTask: (...args: unknown[]) => updateEtlTask(...args),
    previewHttp: (...args: unknown[]) => previewHttp(...args),
  },
}));

vi.mock('@/hooks/use-autocount-etl', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-autocount-etl')>();
  return {
    // `useAutocountEtlTask`/`useHttpPreview` stay REAL - the exact seam B1
    // lived in. Every other hook this editor pulls in is unrelated to the
    // Source-tab Test flow and stays a plain stub (unmocked, it would need
    // its own service wiring for no benefit to this suite).
    ...actual,
    useLineFetcher: () => ({ fetchLines: vi.fn().mockResolvedValue([]) }),
    useAutocountSqlConnections: () => ({
      connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'mssql', database: 'AED_2024' }],
      isLoading: false,
      error: null,
    }),
    useAutocountApiConnections: () => ({
      connections: [
        { id: 'conn-api-mocha', name: 'Mocha REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db2', auth: 'none' as const },
      ],
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
  };
});

vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: null,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: vi.fn(),
    reload: vi.fn(),
    testFormula: vi.fn(),
    simulate: vi.fn(),
  }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

const detailBox = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: detailBox.current,
    isLoading: false,
    notFound: false,
    reload: vi.fn(),
  }),
}));

/** A saved (never previewed this session) HTTP task - `resultColumns: []`,
 * `lastPreviewAt: null` - matches what a real `GET .../etl-task` returns for
 * a task that was configured, then saved, but never Tested. */
function savedHttpTask(overrides: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'company-http',
    entityType: 'product',
    etlStatus: 'draft',
    activatedAt: null,
    sourceImpl: 'autocount_http',
    sourceConfig: {
      connectionId: 'conn-api-mocha',
      query: '',
      lineQuery: null,
      keyColumns: [],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
      path: '/itembypage',
      keyFields: ['ItemCode'],
      watermarkField: 'LastModified',
      comparedFields: [],
      distinctOf: null,
    },
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...overrides,
  };
}

function httpCompanyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'company-http',
      connectionId: 'conn-api-mocha',
      databaseName: 'MOCHA',
      companyName: 'Mocha Sdn Bhd',
      name: 'Mocha',
      isActive: true,
      sinkImpl: 'logging',
      sinkConnectionId: null,
      sorentoCompanyCode: null,
      createdAt: null,
      sourceKind: 'http',
      documentPrerequisites: [],
    },
    entities: [],
  };
}

/** The backend's own stamped-task echo (`HttpPreviewResponse.task`) - the
 * SAVED `sourceConfig` is UNCHANGED (`preview_http` never persists the
 * tested path/connectionId, only `resultColumns`/`lastPreviewAt` on
 * whatever config already exists) - this is exactly the shape that used to
 * trigger B1 when the tested path differed from the saved one. */
function stampedTaskEcho(overrides: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return savedHttpTask({
    resultColumns: ['ItemCode', 'LastModified'],
    lastPreviewAt: '2026-09-12T05:00:00Z',
    ...overrides,
  });
}

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function saveButton() {
  return screen.getByRole('button', { name: /^Save/i });
}
function pathInput() {
  return screen.getByLabelText('Endpoint path');
}
function testButton() {
  return screen.getByTestId('http-test-path');
}
function activateTab() {
  return screen.getByRole('tab', { name: /Review & Activate/i });
}
function activateButton() {
  return screen.getByTestId('etl-activate');
}

beforeEach(() => {
  getEtlTask.mockReset();
  updateEtlTask.mockReset();
  previewHttp.mockReset();
  detailBox.current = httpCompanyDetail();
  getEtlTask.mockResolvedValue(savedHttpTask());
});

describe('TaskEditorView - Source tab Test echoes the stamped task (sprint-5/08 review round 7)', () => {
  it('a successful Test at the SAVED path enables Activate without a remount (AC-08-14/AC-22-18)', async () => {
    previewHttp.mockResolvedValue({
      envelope: 'paged', totalCount: 1, columns: [{ name: 'ItemCode', sample: 'A1' }],
      rows: [{ ItemCode: 'A1' }], durationMs: 20,
      task: stampedTaskEcho(),
    });
    const user = userEvent.setup();
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    // Before any Test, the never-previewed task withholds Activate.
    await user.click(activateTab());
    expect(activateButton()).toBeDisabled();

    await user.click(screen.getByRole('tab', { name: /Source/i }));
    await act(async () => {
      fireEvent.click(testButton());
      await Promise.resolve();
    });

    // Same component instance, only a tab switch - never a remount.
    await user.click(activateTab());
    expect(activateButton()).toBeEnabled();
  });

  it('Save stays ENABLED after a Test at an edited path that differs from the saved one (B1)', async () => {
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    fireEvent.change(pathInput(), { target: { value: '/itembypage2' } });
    expect(saveButton()).toBeDisabled();

    // The backend's echo carries the SAVED path ('/itembypage') - it never
    // persists the tested one - which is exactly what used to re-clobber
    // `httpPreviewedFor` back to the saved pair (B1).
    previewHttp.mockResolvedValue({
      envelope: 'paged', totalCount: 1, columns: [{ name: 'ItemCode', sample: 'A1' }],
      rows: [{ ItemCode: 'A1' }], durationMs: 20,
      task: stampedTaskEcho(),
    });
    await act(async () => {
      fireEvent.click(testButton());
      await Promise.resolve();
    });

    expect(previewHttp).toHaveBeenCalledWith(
      expect.objectContaining({ connectionId: 'conn-api-mocha', path: '/itembypage2' }),
    );
    expect(saveButton()).toBeEnabled();
  });

  it('an unsaved path edit survives the Test (the working draft is never reseeded by the echoed task)', async () => {
    previewHttp.mockResolvedValue({
      envelope: 'paged', totalCount: 1, columns: [{ name: 'ItemCode', sample: 'A1' }],
      rows: [{ ItemCode: 'A1' }], durationMs: 20,
      task: stampedTaskEcho(),
    });
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    fireEvent.change(pathInput(), { target: { value: '/itembypage2' } });
    await act(async () => {
      fireEvent.click(testButton());
      await Promise.resolve();
    });

    expect(pathInput()).toHaveValue('/itembypage2');
  });

  it('a FAILED Test never adopts a task and Save stays disabled', async () => {
    previewHttp.mockRejectedValue(new Error('boom'));
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(testButton());
      await Promise.resolve();
    });

    expect(saveButton()).toBeDisabled();
  });

  /**
   * sprint-5/08 review round 8 - AC-08-20's seed effect only ever ran once,
   * seeding from an ALREADY-provable task the FIRST time the editor mounts.
   * That original AC never pinned a case where the seed itself matters (both
   * this file's and `http-save-gate`'s fixtures used `resultColumns: []`) -
   * this locks in the "re-opening an already-tested task never demands a
   * redundant re-test" half of the contract.
   */
  it('Save is enabled on mount for an already-previewed task, with no Test call (AC-08-20 seed path)', async () => {
    getEtlTask.mockResolvedValue(
      savedHttpTask({ resultColumns: ['ItemCode'], lastPreviewAt: '2026-09-11T00:00:00Z' }),
    );
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    expect(saveButton()).toBeEnabled();
    expect(previewHttp).not.toHaveBeenCalled();
  });

  /**
   * sprint-5/08 review round 8 (B1) - `onCancel` used to leave
   * `httpPreviewedFor` pointed at whatever path the discarded edit had just
   * Tested. Saved `{conn, /itembypage}` (already proved) -> Edit -> change
   * path to `/itembypage2` -> Test succeeds there too -> Cancel (discards
   * back to the saved `/itembypage`) -> Edit again: Save must be enabled for
   * the saved, already-proved config with no further Test.
   */
  it('Save enables after Cancel + a new Edit, following an edit + Test on a DIFFERENT path (round 8)', async () => {
    getEtlTask.mockResolvedValue(
      savedHttpTask({ resultColumns: ['ItemCode'], lastPreviewAt: '2026-09-11T00:00:00Z' }),
    );
    previewHttp.mockResolvedValue({
      envelope: 'paged', totalCount: 1, columns: [{ name: 'ItemCode', sample: 'A1' }],
      rows: [{ ItemCode: 'A1' }], durationMs: 20,
      // The echo carries the SAVED sourceConfig (still `/itembypage`) - the
      // backend never persists the tested-but-unsaved path (round 7's B1).
      task: stampedTaskEcho(),
    });
    const user = userEvent.setup();
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    await user.click(editButton());

    fireEvent.change(pathInput(), { target: { value: '/itembypage2' } });
    await act(async () => {
      fireEvent.click(testButton());
      await Promise.resolve();
    });
    expect(saveButton()).toBeEnabled();

    await user.click(screen.getByRole('button', { name: /^Cancel$/ }));
    await waitFor(() => expect(screen.getByText('Discard changes?')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Discard changes/i }));

    await waitFor(() => expect(editButton()).toBeInTheDocument());
    await user.click(editButton());
    expect(saveButton()).toBeEnabled();
    expect(previewHttp).toHaveBeenCalledTimes(1);
  });
});
