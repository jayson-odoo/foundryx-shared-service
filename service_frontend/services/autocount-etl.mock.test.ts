import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService as service } from './autocount-service.mock';

/**
 * The direct-DB ETL mock IS the phase-2 backend spec (plan 22 S1). These pin
 * the behaviour classes the real endpoints must reproduce: cached schema tree,
 * the SELECT-only guard (422 before the source), sanitized DB errors (400),
 * the 100-row cap with its indicator, a 0-row success, and the draft-task
 * round-trip with a 422 {fieldErrors} on the documents from-date rule.
 */
describe('mock autocount ETL service', () => {
  it('lists only SQL-database connections with their dialect + database', async () => {
    const list = await service.listSqlConnections();
    expect(list.length).toBeGreaterThan(0);
    for (const c of list) {
      expect(c).toMatchObject({
        id: expect.any(String),
        name: expect.any(String),
        database: expect.any(String),
      });
      expect(['mssql', 'postgresql', 'mysql']).toContain(c.dialect);
    }
  });

  it('returns schemas → tables → columns (name + type) for a connection', async () => {
    const schema = await service.getSqlSchema('conn-sql-1');
    expect(schema.connectionId).toBe('conn-sql-1');
    expect(schema.schemas[0].name).toBe('dbo');
    const debtor = schema.schemas[0].tables.find((t) => t.name === 'Debtor');
    expect(debtor?.columns).toContainEqual({ name: 'AccNo', type: 'varchar(12)' });
  });

  it('fails schema introspection with a SANITIZED message on a dead connection', async () => {
    await expect(service.getSqlSchema('conn-sql-down')).rejects.toMatchObject({
      status: 502,
      message: expect.not.stringContaining('conn-sql-down'),
    });
  });

  it('rejects anything but a single SELECT/WITH with 422 (AC-22-03)', async () => {
    for (const bad of [
      'DELETE FROM dbo.Debtor',
      'UPDATE dbo.Debtor SET IsActive = 1',
      'SELECT 1; SELECT 2',
      'EXEC sp_who',
      '',
    ]) {
      await expect(service.previewSqlQuery('conn-sql-1', bad)).rejects.toMatchObject({
        status: 422,
      });
    }
    await expect(
      service.previewSqlQuery('conn-sql-1', 'WITH d AS (SELECT * FROM dbo.Debtor) SELECT * FROM d'),
    ).resolves.toMatchObject({ rowCount: 100 });
  });

  it('caps the preview at 100 rows and flags the truncation (AC-22-06)', async () => {
    const preview = await service.previewSqlQuery('conn-sql-1', 'SELECT * FROM dbo.Debtor');
    expect(preview.rows).toHaveLength(100);
    expect(preview.rowCount).toBe(100);
    expect(preview.truncated).toBe(true);
    expect(preview.columns.map((c) => c.name)).toEqual([
      'AccNo',
      'CompanyName',
      'Phone1',
      'EmailAddress',
      'IsActive',
      'LastModified',
    ]);
    expect(preview.columns[0].type).toBe('varchar(12)');
  });

  it('returns a 0-row SUCCESS (columns still known) for an empty table', async () => {
    const preview = await service.previewSqlQuery('conn-sql-1', 'select * from Location');
    expect(preview.rowCount).toBe(0);
    expect(preview.rows).toEqual([]);
    expect(preview.truncated).toBe(false);
    expect(preview.columns.length).toBeGreaterThan(0);
  });

  it('surfaces a failing query as a sanitized 400 (no DSN echo)', async () => {
    await expect(
      service.previewSqlQuery('conn-sql-1', 'SELECT * FROM dbo.Nope'),
    ).rejects.toMatchObject({ status: 400, message: "Invalid object name 'Nope'." });
  });

  it('serves a DRAFT task with defaults for a never-configured entity', async () => {
    const task = await service.getEtlTask('company-x', 'customer');
    expect(task.etlStatus).toBe('draft');
    expect(task.sourceConfig).toMatchObject({
      query: '',
      lineQuery: null,
      keyColumns: [],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
    });
    const so = await service.getEtlTask('company-x', 'sales_order');
    expect(so.sourceConfig.lineQuery).toBe('');
    expect(so.sourceConfig.fromDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('round-trips a draft save', async () => {
    const task = await service.getEtlTask('company-rt', 'customer');
    const saved = await service.updateEtlTask('company-rt', 'customer', {
      sourceConfig: {
        ...task.sourceConfig,
        query: 'SELECT * FROM dbo.Debtor',
        keyColumns: ['AccNo'],
        watermarkColumn: 'LastModified',
        comparedColumns: ['CompanyName'],
      },
    });
    expect(saved.sourceConfig.keyColumns).toEqual(['AccNo']);
    const again = await service.getEtlTask('company-rt', 'customer');
    expect(again.sourceConfig.query).toBe('SELECT * FROM dbo.Debtor');
    expect(again.sourceConfig.watermarkColumn).toBe('LastModified');
  });

  it('422s with fieldErrors when a document task has no from-date (AC-22-11)', async () => {
    const task = await service.getEtlTask('company-doc', 'sales_order');
    let caught: unknown;
    try {
      await service.updateEtlTask('company-doc', 'sales_order', {
        sourceConfig: { ...task.sourceConfig, fromDate: null },
      });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
    expect((caught as ApiError).detail).toEqual({
      fieldErrors: { fromDate: expect.any(String) },
    });
  });
});
