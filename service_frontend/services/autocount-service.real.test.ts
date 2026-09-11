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
});
