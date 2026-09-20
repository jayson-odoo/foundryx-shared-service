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

  it('previewEtlTask normalizes the embedded task the same way as getEtlTask', async () => {
    apiFetchMock.mockResolvedValue({
      task: realHttpTaskWire(),
      preview: { columns: [], rows: [], truncated: false },
    });
    const result = await realAutocountService.previewEtlTask('company-1', 'product');
    expect(result.task.sourceConfig.query).toBe('');
    expect(result.task.sourceConfig.docDateColumn).toBeNull();
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
