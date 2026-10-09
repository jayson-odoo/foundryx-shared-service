import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService as service, resetEtlMockState } from './autocount-service.mock';

/**
 * The plan 22 S2 mock IS the phase-2 backend spec: the sink-target company
 * code guard (Appendix A6), the `sourceImpl` switch, the activate-once gate
 * (preview → activate, 409 without), pause/resume, Run now + run history, and
 * the anchor 422 landing as a TASK-level error (never per record).
 */

const COMPANY = 'company-s2';
const ENTITY = 'customer';

async function savedTask() {
  const task = await service.getEtlTask(COMPANY, ENTITY);
  return service.updateEtlTask(COMPANY, ENTITY, {
    sourceConfig: {
      ...task.sourceConfig,
      query: 'SELECT * FROM dbo.Debtor',
      keyColumns: ['AccNo'],
      watermarkColumn: 'LastModified',
    },
  });
}

async function sorentoCompany(code: string | null) {
  return service.updateSinkTarget(COMPANY, {
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-9',
    sorentoCompanyCode: code,
  });
}

async function rejected(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    return e as ApiError;
  }
  throw new Error('expected a rejection');
}

beforeEach(() => resetEtlMockState());

describe('sink target company code (Appendix A6)', () => {
  it('requires the Sorento company code with a sorento sink - 422 {fieldErrors}', async () => {
    const err = await rejected(sorentoCompany('  '));
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { sorentoCompanyCode: expect.any(String) } });
  });

  it('stores it trimmed and echoes it on the company; logging nulls it', async () => {
    const saved = await sorentoCompany(' SRT ');
    expect(saved.sorentoCompanyCode).toBe('SRT');
    expect((await service.getCompany(COMPANY)).company.sorentoCompanyCode).toBe('SRT');
    const cleared = await service.updateSinkTarget(COMPANY, { sinkImpl: 'logging' });
    expect(cleared.sorentoCompanyCode).toBeNull();
  });
});

describe('source switch (AC-22-08)', () => {
  it('persists sourceImpl through the entity-config update and rejects unknowns', async () => {
    const entity = await service.updateEntityConfig(COMPANY, ENTITY, { sourceImpl: 'sql_db' });
    expect(entity.sourceImpl).toBe('sql_db');
    const detail = await service.getCompany(COMPANY);
    expect(detail.entities.find((e) => e.entityType === ENTITY)?.sourceImpl).toBe('sql_db');
    await expect(
      service.updateEntityConfig(COMPANY, ENTITY, {
        sourceImpl: 'csv' as unknown as 'sql_db',
      }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('pauses an ACTIVE task when its entity is switched back to the API path', async () => {
    await sorentoCompany('SRT');
    await savedTask();
    await service.previewEtlTask(COMPANY, ENTITY);
    await service.activateEtlTask(COMPANY, ENTITY);
    await service.updateEntityConfig(COMPANY, ENTITY, { sourceImpl: 'autocount_read' });
    expect((await service.getEtlTask(COMPANY, ENTITY)).etlStatus).toBe('paused');
  });
});

describe('task read-only fields', () => {
  it('derives resultColumns from the preview of the saved query and clears lastPreviewAt on save', async () => {
    await sorentoCompany('SRT');
    await service.previewSqlQuery('conn-sql-1', 'SELECT * FROM dbo.Debtor');
    const saved = await savedTask();
    expect(saved.resultColumns).toEqual([
      'AccNo',
      'CompanyName',
      'Phone1',
      'EmailAddress',
      'IsActive',
      'LastModified',
    ]);
    const previewed = await service.previewEtlTask(COMPANY, ENTITY);
    expect(previewed.task.lastPreviewAt).toEqual(expect.any(String));
    const resaved = await savedTask();
    expect(resaved.lastPreviewAt).toBeNull();
  });

  it('falls back to the saved picks when the query was never previewed this session', async () => {
    const saved = await savedTask();
    expect(saved.resultColumns).toEqual(['AccNo', 'LastModified']);
  });
});

describe('preview (AC-22-18, Appendix A6)', () => {
  it('409s before a query with key columns is saved', async () => {
    await sorentoCompany('SRT');
    const err = await rejected(service.previewEtlTask(COMPANY, ENTITY));
    expect(err.status).toBe(409);
  });

  it('is "nothing to preview" for a logging company', async () => {
    await savedTask();
    const res = await service.previewEtlTask(COMPANY, ENTITY);
    expect(res.preview.previewable).toBe(false);
    expect(res.task.lastPreviewAt).toBeNull();
  });

  it('surfaces each Sorento anchor 422 as a task-level {code, message}', async () => {
    await savedTask();
    for (const [code, expected] of [
      ['UNKNOWN', 'UNKNOWN_COMPANY'],
      ['AMBIG-1', 'COMPANY_ANCHOR_AMBIGUOUS'],
    ] as const) {
      await sorentoCompany(code);
      const err = await rejected(service.previewEtlTask(COMPANY, ENTITY));
      expect(err.status).toBe(422);
      expect(err.detail).toMatchObject({ code: expected, message: expect.any(String) });
    }
  });

  it('a legacy sorento company with a backfilled-NULL code gets COMPANY_ANCHOR_REQUIRED', async () => {
    const legacy = 'company-legacy';
    const task = await service.getEtlTask(legacy, ENTITY);
    await service.updateEtlTask(legacy, ENTITY, {
      sourceConfig: { ...task.sourceConfig, query: 'SELECT * FROM dbo.Debtor', keyColumns: ['AccNo'] },
    });
    const company = (await service.getCompany(legacy)).company;
    expect(company.sinkImpl).toBe('sorento');
    expect(company.sorentoCompanyCode).toBeNull();
    const err = await rejected(service.previewEtlTask(legacy, ENTITY));
    expect(err.status).toBe(422);
    expect(err.detail).toMatchObject({ code: 'COMPANY_ANCHOR_REQUIRED' });
  });

  it('502s when the consumer is unreachable and never stamps lastPreviewAt', async () => {
    await savedTask();
    await sorentoCompany('DOWN');
    const err = await rejected(service.previewEtlTask(COMPANY, ENTITY));
    expect(err.status).toBe(502);
    expect((await service.getEtlTask(COMPANY, ENTITY)).lastPreviewAt).toBeNull();
  });

  it('returns the batch-review preview shape and stamps lastPreviewAt on success', async () => {
    await savedTask();
    await sorentoCompany('SRT');
    const res = await service.previewEtlTask(COMPANY, ENTITY);
    expect(res.preview.previewable).toBe(true);
    if (res.preview.previewable) {
      expect(res.preview.summary).toMatchObject({ total: 172, created: 134, updated: 38 });
      expect(res.preview.predictions.length).toBeGreaterThan(0);
    }
    expect(res.task.lastPreviewAt).toEqual(expect.any(String));
  });
});

describe('activate / pause / resume / run (AC-22-18/19)', () => {
  it('refuses to activate without a successful preview (409)', async () => {
    await savedTask();
    await sorentoCompany('SRT');
    expect((await rejected(service.activateEtlTask(COMPANY, ENTITY))).status).toBe(409);
  });

  it('activates after a preview, then pauses and resumes without re-preview', async () => {
    await savedTask();
    await sorentoCompany('SRT');
    await service.previewEtlTask(COMPANY, ENTITY);
    const active = await service.activateEtlTask(COMPANY, ENTITY);
    expect(active.etlStatus).toBe('active');
    expect(active.activatedAt).toEqual(expect.any(String));
    expect((await rejected(service.resumeEtlTask(COMPANY, ENTITY))).status).toBe(409);
    expect((await service.pauseEtlTask(COMPANY, ENTITY)).etlStatus).toBe('paused');
    expect((await rejected(service.pauseEtlTask(COMPANY, ENTITY))).status).toBe(409);
    expect((await service.resumeEtlTask(COMPANY, ENTITY)).etlStatus).toBe('active');
  });

  it('lists run history (newest first, cost columns, skipped reason) only once active', { timeout: 15_000 }, async () => {
    await savedTask();
    expect((await service.listEtlRuns(COMPANY, ENTITY)).total).toBe(0);
    await sorentoCompany('SRT');
    await service.previewEtlTask(COMPANY, ENTITY);
    await service.activateEtlTask(COMPANY, ENTITY);
    const runs = await service.listEtlRuns(COMPANY, ENTITY, { page: 0, pageSize: 25 });
    expect(runs.total).toBeGreaterThanOrEqual(6);
    const modes = runs.data.map((r) => r.mode);
    expect(modes).toEqual(expect.arrayContaining(['manual', 'incremental', 'reconcile', 'skipped']));
    const skipped = runs.data.find((r) => r.mode === 'skipped')!;
    expect(skipped.outcome).toBe('SKIPPED');
    expect(skipped.jobId).toBeNull();
    expect(skipped.skipReason).toEqual(expect.any(String));
    const failed = runs.data.find((r) => r.outcome === 'FAILED')!;
    expect(failed.error).toContain('Delete guard');
    for (const r of runs.data) {
      expect(r).toMatchObject({
        rowsScanned: expect.any(Number),
        addedCount: expect.any(Number),
        updatedCount: expect.any(Number),
        deletedCount: expect.any(Number),
      });
    }
    const paged = await service.listEtlRuns(COMPANY, ENTITY, { page: 1, pageSize: 4 });
    expect(paged.data.length).toBe(runs.total - 4);
  });

  it('Run now needs an active task, prepends a manual run, and surfaces an anchor failure on the TASK', async () => {
    await savedTask();
    await sorentoCompany('SRT');
    expect((await rejected(service.runEtlTaskNow(COMPANY, ENTITY))).status).toBe(409);
    await service.previewEtlTask(COMPANY, ENTITY);
    await service.activateEtlTask(COMPANY, ENTITY);

    const ok = await service.runEtlTaskNow(COMPANY, ENTITY);
    expect(ok.runId).toEqual(expect.any(String));
    expect(ok.task.lastRunError).toBeNull();
    expect((await service.listEtlRuns(COMPANY, ENTITY)).data[0]).toMatchObject({
      id: ok.runId,
      mode: 'manual',
      outcome: 'SUCCESS',
    });

    // The company code changed underneath an active task - the next run fails
    // as a whole with the anchor code, never as per-record failures.
    await sorentoCompany('UNKNOWN');
    const bad = await service.runEtlTaskNow(COMPANY, ENTITY);
    expect(bad.task.lastRunErrorCode).toBe('UNKNOWN_COMPANY');
    expect(bad.task.lastRunError).toEqual(expect.any(String));
    const latest = (await service.listEtlRuns(COMPANY, ENTITY)).data[0];
    expect(latest.outcome).toBe('FAILED');
    expect(latest.failedCount).toBe(0);
  }, 15_000);
});
