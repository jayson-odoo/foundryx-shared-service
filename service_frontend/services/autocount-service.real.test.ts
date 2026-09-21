/**
 * Real AutoCount service - wire-boundary normalization (sprint-5/08 review
 * round 1, S5 live-verify).
 *
 * DEFECT found live (not a mock artifact): `default_http_source_config()`
 * (`modules/autocount/services/etl_service.py`) deliberately never merges
 * the SQL-shape keys onto an `autocount_http` task's `sourceConfig`
 * (AC-08-30 - "never a stray SQL key round-trips onto an HTTP task's wire
 * config"). A REAL saved HTTP task's `GET .../etl-task` therefore omits
 * `query`/`lineQuery`/`keyColumns`/`watermarkColumn`/`comparedColumns`/
 * `fromDate`/`docDateColumn`/`filterFormula` entirely, even though
 * `AutocountEtlSourceConfig` declares them non-optional (the mock always
 * filled them) and `task-editor-view.tsx`'s baseline dirty-check reads
 * `seeded.query.trim()` unguarded - this crashed "Cannot read properties of
 * undefined (reading 'trim')" live-verifying AC-08-21 (Add entity -> Test
 * -> Save on a fresh HTTP task) before this fix.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountEtlTask } from '@/types/autocount';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args),
  };
});

import { realAutocountService } from './autocount-service.real';

beforeEach(() => {
  apiFetchMock.mockReset();
});

/** The SHAPE a real `autocount_http` task's `GET .../etl-task` answers -
 * the SQL keys genuinely absent, not merely empty. */
function realHttpTaskWire(): Partial<AutocountEtlTask> {
  return {
    companyId: 'company-1',
    entityType: 'product',
    etlStatus: 'draft',
    activatedAt: null,
    sourceImpl: 'autocount_http',
    sourceConfig: {
      connectionId: 'conn-api-mocha',
      path: '/itembypage',
      keyFields: ['ItemCode'],
      watermarkField: 'LastModified',
      comparedFields: [],
      distinctOf: null,
      incrementalMinutes: 15,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
      // NO query/lineQuery/keyColumns/watermarkColumn/comparedColumns/
      // fromDate/docDateColumn/filterFormula - the real backend shape.
    } as never,
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

describe('realAutocountService - HTTP task sourceConfig normalization', () => {
  it('getEtlTask fills the SQL-shape keys the real backend omits for an autocount_http task', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const task = await realAutocountService.getEtlTask('company-1', 'product');
    expect(task.sourceConfig.query).toBe('');
    expect(task.sourceConfig.lineQuery).toBeNull();
    expect(task.sourceConfig.keyColumns).toEqual([]);
    expect(task.sourceConfig.watermarkColumn).toBeNull();
    expect(task.sourceConfig.comparedColumns).toEqual([]);
    expect(task.sourceConfig.fromDate).toBeNull();
    expect(task.sourceConfig.docDateColumn).toBeNull();
    expect(task.sourceConfig.filterFormula).toBeNull();
    // The HTTP fields the server DID send stay exactly as received.
    expect(task.sourceConfig.path).toBe('/itembypage');
    expect(task.sourceConfig.keyFields).toEqual(['ItemCode']);
  });

  it('updateEtlTask normalizes the PUT response the same way', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const task = await realAutocountService.updateEtlTask('company-1', 'product', {
      sourceConfig: realHttpTaskWire().sourceConfig as never,
      sourceImpl: 'autocount_http',
    });
    expect(task.sourceConfig.query).toBe('');
    expect(task.sourceConfig.keyColumns).toEqual([]);
  });

  it('never overwrites a value the server DID send (SQL task keeps its real query)', async () => {
    apiFetchMock.mockResolvedValue({
      ...realHttpTaskWire(),
      sourceImpl: 'sql_db',
      sourceConfig: { query: 'SELECT 1', keyColumns: ['id'] } as never,
    });
    const task = await realAutocountService.getEtlTask('company-1', 'customer');
    expect(task.sourceConfig.query).toBe('SELECT 1');
    expect(task.sourceConfig.keyColumns).toEqual(['id']);
  });

  /**
   * Round 5 defect (tester, live at d696daba): clicking Activate (once also
   * Run now) on a real `autocount_http` task crashed the page with
   * "Cannot read properties of undefined (reading 'trim')" the first time
   * the task's status transitioned in place. Root cause: `activateEtlTask` /
   * `pauseEtlTask` / `resumeEtlTask` / `runEtlTaskNow` / `previewEtlTask`
   * answer the SAME real-backend shape as `getEtlTask` (SQL-shape keys
   * omitted for an http task) but never ran it through `normalizeEtlTask` -
   * only `getEtlTask`/`updateEtlTask` did. `task-editor-view.tsx` then adopts
   * that un-normalized task via `apply()`, and `task.sourceConfig.query.trim()`
   * throws.
   */
  it('activateEtlTask normalizes the response the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const task = await realAutocountService.activateEtlTask('company-1', 'product');
    expect(task.sourceConfig.query).toBe('');
    expect(task.sourceConfig.keyColumns).toEqual([]);
    expect(task.sourceConfig.path).toBe('/itembypage');
  });

  it('pauseEtlTask normalizes the response the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const task = await realAutocountService.pauseEtlTask('company-1', 'product');
    expect(task.sourceConfig.query).toBe('');
    expect(task.sourceConfig.watermarkColumn).toBeNull();
  });

  it('resumeEtlTask normalizes the response the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const task = await realAutocountService.resumeEtlTask('company-1', 'product');
    expect(task.sourceConfig.query).toBe('');
    expect(task.sourceConfig.comparedColumns).toEqual([]);
  });

  it('runEtlTaskNow normalizes the embedded task the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue({
      runId: 'run-1',
      jobId: 'job-1',
      status: 'done',
      task: realHttpTaskWire(),
    });
    const started = await realAutocountService.runEtlTaskNow('company-1', 'product');
    expect(started.task.sourceConfig.query).toBe('');
    expect(started.task.sourceConfig.fromDate).toBeNull();
  });

  // sprint-5/11 review round 2 (item 6) - `previewEtlTask` removed from
  // `realAutocountService` (dead since S4's job-based preview surface
  // replaced the synchronous `.../preview` route this test exercised).

  /**
   * S7-lite P0 (real-worker smoke, evidence `documentation/plans/
   * sprint-5/11-evidence/s7-lite/README.md`) - `getPreviewJob`/
   * `cancelPreviewJob` echo a `full`-scope job's DONE task through the
   * backend's own `_task_echo`/`_task_response` builder
   * (`modules/autocount/preview_job.py`), the SAME un-normalized shape as
   * `getEtlTask` (AC-08-30). Neither ran the echo through `normalizeEtlTask`
   * - `hooks/use-autocount-etl.ts:245`'s `onTask(job.result.task)` then
   * landed the raw shape straight into the shared `task` state, and
   * `task-editor-view.tsx`'s `task.sourceConfig.query.trim()` (no `?.`)
   * crashed the whole Review & Activate page to the error boundary the
   * first time a preview job completed for a real `autocount_http` task.
   */
  it('getPreviewJob normalizes a done full-scope job\'s echoed task the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue({
      id: 'preview-job-1',
      scope: 'full',
      status: 'done',
      progress: null,
      result: { scope: 'full', task: realHttpTaskWire(), preview: { columns: [], rows: [], truncated: false } },
      error: null,
      taskError: null,
      createdAt: '2026-09-21T00:00:00Z',
    });
    const job = await realAutocountService.getPreviewJob('preview-job-1');
    if (job.result?.scope !== 'full') throw new Error('expected a full-scope result');
    expect(job.result.task.sourceConfig.query).toBe('');
    expect(job.result.task.sourceConfig.lineQuery).toBeNull();
    expect(job.result.task.sourceConfig.keyColumns).toEqual([]);
    expect(job.result.task.sourceConfig.watermarkColumn).toBeNull();
    expect(job.result.task.sourceConfig.comparedColumns).toEqual([]);
    expect(job.result.task.sourceConfig.fromDate).toBeNull();
    expect(job.result.task.sourceConfig.docDateColumn).toBeNull();
    expect(job.result.task.sourceConfig.filterFormula).toBeNull();
    // The HTTP fields the server DID send stay exactly as received.
    expect(job.result.task.sourceConfig.path).toBe('/itembypage');
    expect(job.result.task.sourceConfig.keyFields).toEqual(['ItemCode']);
  });

  it('cancelPreviewJob normalizes a done full-scope job\'s echoed task the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue({
      id: 'preview-job-1',
      scope: 'full',
      status: 'done',
      progress: null,
      result: { scope: 'full', task: realHttpTaskWire(), preview: { columns: [], rows: [], truncated: false } },
      error: null,
      taskError: null,
      createdAt: '2026-09-21T00:00:00Z',
    });
    const job = await realAutocountService.cancelPreviewJob('preview-job-1');
    if (job.result?.scope !== 'full') throw new Error('expected a full-scope result');
    expect(job.result.task.sourceConfig.query).toBe('');
    expect(job.result.task.sourceConfig.keyColumns).toEqual([]);
  });

  it('getPreviewJob leaves a sample-scope job (no task to normalize) untouched', async () => {
    const payload = {
      id: 'preview-job-2',
      scope: 'sample',
      status: 'done',
      progress: null,
      result: { scope: 'sample', preview: { columns: [], rows: [], truncated: false } },
      error: null,
      taskError: null,
      createdAt: '2026-09-21T00:00:00Z',
    };
    apiFetchMock.mockResolvedValue(payload);
    const job = await realAutocountService.getPreviewJob('preview-job-2');
    expect(job).toEqual(payload);
  });

  it('getPreviewJob leaves a still-running job (no result yet) untouched', async () => {
    const payload = {
      id: 'preview-job-3',
      scope: 'full',
      status: 'running',
      progress: { stage: 'source', pagesDone: 1, pagesTotal: 4 },
      result: null,
      error: null,
      taskError: null,
      createdAt: '2026-09-21T00:00:00Z',
    };
    apiFetchMock.mockResolvedValue(payload);
    const job = await realAutocountService.getPreviewJob('preview-job-3');
    expect(job).toEqual(payload);
  });

  it('startPreviewJob passes the 202 body through untouched (no result/task to normalize)', async () => {
    apiFetchMock.mockResolvedValue({ jobId: 'preview-job-4', status: 'queued' });
    const started = await realAutocountService.startPreviewJob({
      scope: 'full',
      companyId: 'company-1',
      entityType: 'product',
    });
    expect(started).toEqual({ jobId: 'preview-job-4', status: 'queued' });
  });
});

// sprint-5/10 review round 1, item 5 - the `lookups` save round trip
// (`EtlSourceConfigIn.lookups: Optional[...] = None` - omit the key on the
// wire to KEEP whatever is stored; only an explicit `[]` clears it, per the
// backend docstring `services/etl_service.py`).
describe('realAutocountService - lookups save round trip (AC-10-01)', () => {
  it('an untouched editor omits the key entirely - the backend keeps what it has', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const { lookups: _omit, ...configWithoutLookups } = { ...realHttpTaskWire().sourceConfig } as never;
    void _omit;
    await realAutocountService.updateEtlTask('company-1', 'product', {
      sourceConfig: configWithoutLookups as never,
      sourceImpl: 'autocount_http',
    });
    const body = JSON.parse(apiFetchMock.mock.calls[0][1].body);
    expect(Object.prototype.hasOwnProperty.call(body.sourceConfig, 'lookups')).toBe(false);
  });

  it('clearing every lookup row sends an explicit [] (never omitted)', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    await realAutocountService.updateEtlTask('company-1', 'product', {
      sourceConfig: { ...realHttpTaskWire().sourceConfig, lookups: [] } as never,
      sourceImpl: 'autocount_http',
    });
    const body = JSON.parse(apiFetchMock.mock.calls[0][1].body);
    expect(body.sourceConfig.lookups).toEqual([]);
  });

  it('an edited lookup set sends the whole array', async () => {
    apiFetchMock.mockResolvedValue(realHttpTaskWire());
    const lookups = [
      {
        path: '/itemuombypage',
        as: 'uom',
        on: [{ local: 'ItemCode', remote: 'ItemCode' }],
        fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
      },
    ];
    await realAutocountService.updateEtlTask('company-1', 'product', {
      sourceConfig: { ...realHttpTaskWire().sourceConfig, lookups } as never,
      sourceImpl: 'autocount_http',
    });
    const body = JSON.parse(apiFetchMock.mock.calls[0][1].body);
    expect(body.sourceConfig.lookups).toEqual(lookups);
  });
});

// sprint-5/10 S6 phase 2 swap - pins every route path + method against the
// LIVE backend contract (`modules/autocount/routers/{companies,pull}.py`,
// `.../schemas.py`); the human-invoked pull surface stopped going through
// `withPhase1PullMock` and now hits `realAutocountService` for real.
describe('realAutocountService - human-invoked pull (AC-10-11/27..38)', () => {
  it('setDeliveryMode PUTs the delivery-mode sub-resource', async () => {
    apiFetchMock.mockResolvedValue({ id: 'e1', entityType: 'product', deliveryMode: 'pull' });
    await realAutocountService.setDeliveryMode('company-1', 'product', 'pull');
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/autocount/companies/company-1/entities/product/delivery-mode',
      { method: 'PUT', body: JSON.stringify({ deliveryMode: 'pull' }) },
    );
  });

  it('listPullKeys GETs the tenant key list', async () => {
    apiFetchMock.mockResolvedValue([]);
    await realAutocountService.listPullKeys();
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/keys');
  });

  it('issuePullKey POSTs name + companyIds', async () => {
    apiFetchMock.mockResolvedValue({ key: { id: 'k1' }, plaintext: 'fxa_live_x' });
    await realAutocountService.issuePullKey({ name: 'Sorento', companyIds: ['c1'] });
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/keys', {
      method: 'POST',
      body: JSON.stringify({ name: 'Sorento', companyIds: ['c1'] }),
    });
  });

  it('revokePullKey POSTs the revoke sub-resource', async () => {
    apiFetchMock.mockResolvedValue({ id: 'k1', revokedAt: '2026-09-20T00:00:00Z' });
    await realAutocountService.revokePullKey('k1');
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/keys/k1/revoke', { method: 'POST' });
  });

  it('listPullSnapshots GETs with page/pageSize and the optional company/entity filters', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0, page: 0 });
    await realAutocountService.listPullSnapshots({
      page: 1,
      pageSize: 50,
      companyId: 'c1',
      entityType: 'product',
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/autocount/pull/snapshots?page=1&page_size=50&companyId=c1&entityType=product',
    );
  });

  it('getPullSnapshot GETs the snapshot by id', async () => {
    apiFetchMock.mockResolvedValue({ id: 's1' });
    await realAutocountService.getPullSnapshot('s1');
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/snapshots/s1');
  });

  it('getPullSnapshotRows GETs a 1-based page (the gateway/operator route convention, distinct from the list routes\' 0-based page)', async () => {
    apiFetchMock.mockResolvedValue({
      snapshotId: 's1',
      page: 1,
      pageSize: 1000,
      totalPages: 1,
      recordCount: 0,
      rows: [],
    });
    await realAutocountService.getPullSnapshotRows('s1', 0, 1000);
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/snapshots/s1/rows?page=1&pageSize=1000');
  });

  it('buildPullSnapshot POSTs companyId + entityType to the snapshots collection', async () => {
    apiFetchMock.mockResolvedValue({ id: 's1', status: 'building' });
    await realAutocountService.buildPullSnapshot('c1', 'product');
    expect(apiFetchMock).toHaveBeenCalledWith('/autocount/pull/snapshots', {
      method: 'POST',
      body: JSON.stringify({ companyId: 'c1', entityType: 'product' }),
    });
  });
});
