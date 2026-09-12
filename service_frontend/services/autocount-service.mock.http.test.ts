import { beforeEach, describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService as service, resetEtlMockState } from './autocount-service.mock';

/**
 * The open REST API source PHASE 1 MOCK (sprint-5/08, S1) - the mock IS the
 * backend spec; see the contract block atop `autocount-service.ts`.
 */

beforeEach(() => resetEtlMockState());

async function rejected(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    if (e instanceof ApiError) return e;
  }
  throw new Error('Expected an ApiError to be thrown.');
}

describe('listApiConnections (AC-08-15)', () => {
  it('lists every autocount connection, badged by auth, bound or not', async () => {
    const connections = await service.listApiConnections();
    expect(connections.map((c) => c.id)).toEqual(
      expect.arrayContaining(['conn-api-sorento', 'conn-api-mocha', 'conn-api-vendor']),
    );
    const sorento = connections.find((c) => c.id === 'conn-api-sorento')!;
    expect(sorento.auth).toBe('none');
    expect(sorento.baseUrl).toBe('https://hapi.sorento.cc.cd/api/db1');
    const vendor = connections.find((c) => c.id === 'conn-api-vendor')!;
    expect(vendor.auth).toBe('basic');
  });
});

describe('previewHttp (AC-08-14/22, D14 page walk)', () => {
  it('a paged envelope reports totalCount + sample rows/columns', async () => {
    const preview = await service.previewHttp({ connectionId: 'conn-api-sorento', path: '/itembypage' });
    expect(preview.envelope).toBe('paged');
    expect(preview.totalCount).toBe(11826);
    expect(preview.rows.length).toBeGreaterThan(0);
    expect(preview.rows.length).toBeLessThanOrEqual(50);
    expect(preview.columns.map((c) => c.name)).toEqual(
      expect.arrayContaining(['ItemCode', 'Description', 'ItemGroup', 'ItemBrand', 'LastModified']),
    );
  });

  it('a list envelope carries no totalCount', async () => {
    const preview = await service.previewHttp({ connectionId: 'conn-api-sorento', path: '/ItemGroup' });
    expect(preview.envelope).toBe('list');
    expect(preview.totalCount).toBeUndefined();
    expect(preview.rows.length).toBe(50);
  });

  it('distinctOf projects to a single `value` column, deduped', async () => {
    const preview = await service.previewHttp({
      connectionId: 'conn-api-sorento',
      path: '/itembypage',
      distinctOf: ['BaseUOM', 'SalesUOM', 'PurchaseUOM'],
    });
    expect(preview.columns).toEqual([{ name: 'value', sample: expect.any(String) }]);
    for (const row of preview.rows) {
      expect(Object.keys(row)).toEqual(['value']);
    }
    const values = preview.rows.map((r) => r.value);
    expect(new Set(values).size).toBe(values.length);
  });

  it('422s on a bad path, naming the field', async () => {
    const err = await rejected(
      service.previewHttp({ connectionId: 'conn-api-sorento', path: '/bogus' }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { path: expect.any(String) } });
  });

  it('422s a path with ".." or a query string', async () => {
    const dotdot = await rejected(
      service.previewHttp({ connectionId: 'conn-api-sorento', path: '/../etc' }),
    );
    expect(dotdot.status).toBe(422);
    const query = await rejected(
      service.previewHttp({ connectionId: 'conn-api-sorento', path: '/itembypage?page=1' }),
    );
    expect(query.status).toBe(422);
  });

  it('422s on connectionId for a basic-auth or unknown connection', async () => {
    const basic = await rejected(
      service.previewHttp({ connectionId: 'conn-api-vendor', path: '/itembypage' }),
    );
    expect(basic.status).toBe(422);
    expect(basic.detail).toEqual({ fieldErrors: { connectionId: expect.any(String) } });
    const unknown = await rejected(
      service.previewHttp({ connectionId: 'conn-nope', path: '/itembypage' }),
    );
    expect(unknown.status).toBe(422);
  });
});

describe('createCompany - open (no-auth) connection (AC-08-06/07)', () => {
  it('creates an open company keyed on the operator-typed reference prefix', async () => {
    const company = await service.createCompany({
      connectionId: 'conn-api-sorento',
      name: 'Sorento REST',
      refPrefix: 'SORENTO_TEST',
    });
    expect(company.sourceKind).toBe('http');
    expect(company.databaseName).toBe('SORENTO_TEST');
    expect(company.connectionId).toBe('conn-api-sorento');
  });

  it('422s on refPrefix when blank', async () => {
    const err = await rejected(
      service.createCompany({ connectionId: 'conn-api-sorento', refPrefix: '' }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { refPrefix: expect.any(String) } });
  });

  it('422s on refPrefix in the wrong format', async () => {
    const err = await rejected(
      service.createCompany({ connectionId: 'conn-api-sorento', refPrefix: 'm' }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { refPrefix: expect.any(String) } });
  });

  it('409s a connection already bound to a company', async () => {
    const err = await rejected(
      service.createCompany({ connectionId: 'conn-api-mocha', refPrefix: 'DUPE' }),
    );
    expect(err.status).toBe(409);
  });

  it('409s a duplicate reference prefix, naming the holder (the seeded Mocha company already holds MOCHA)', async () => {
    const err = await rejected(
      service.createCompany({ connectionId: 'conn-api-sorento', refPrefix: 'MOCHA' }),
    );
    expect(err.status).toBe(409);
    expect(err.message).toContain('MOCHA');
    expect(err.detail).toEqual({ fieldErrors: { refPrefix: expect.any(String) } });
  });

  it('an open company has NO seeded entities, mirroring the DB branch (D13)', async () => {
    const company = await service.createCompany({
      connectionId: 'conn-api-sorento',
      refPrefix: 'FRESH',
    });
    const detail = await service.getCompany(company.id);
    expect(detail.entities).toEqual([]);
  });
});

describe('the seeded Mocha company (open, no database)', () => {
  it('reports sourceKind http and the reference-prefix database name', async () => {
    const detail = await service.getCompany('company-http');
    expect(detail.company.sourceKind).toBe('http');
    expect(detail.company.databaseName).toBe('MOCHA');
    expect(detail.company.connectionId).toBe('conn-api-mocha');
    expect(detail.entities).toEqual([]);
  });

  it('is excluded from listApiConnections\' unbound view via the connect-form hook contract', async () => {
    // listApiConnections itself returns every connection (bound or not, see
    // its own describe block) - the connect form's hook does the exclusion.
    const companies = await service.listCompanies({ page: 0, pageSize: 200 });
    const bound = new Set(companies.data.map((c) => c.connectionId));
    expect(bound.has('conn-api-mocha')).toBe(true);
  });
});

describe('getEtlTask - blank draft on a non-db company (sprint-5/08 fix - latent SQL-default bug)', () => {
  it("a fresh open company's never-configured task has connectionId null, not an arbitrary SQL connection", async () => {
    const task = await service.getEtlTask('company-http', 'brand');
    expect(task.sourceConfig.connectionId).toBeNull();
  });

  it("a fresh basic-auth (`api`-kind) company's blank task also has connectionId null (regression: used to silently pre-fill conn-sql-1)", async () => {
    const task = await service.getEtlTask('company-1', 'warehouse');
    expect(task.sourceConfig.connectionId).toBeNull();
  });
});

describe('updateEtlTask - autocount_http (sprint-5/08 D13/D5, AC-08-28)', () => {
  it('a Mocha task saves an HTTP source (connectionId/path/keyFields), reporting sourceImpl back', async () => {
    const task = await service.getEtlTask('company-http', 'product');
    const saved = await service.updateEtlTask('company-http', 'product', {
      sourceImpl: 'autocount_http',
      sourceConfig: {
        ...task.sourceConfig,
        connectionId: 'conn-api-mocha',
        path: '/itembypage',
        keyFields: ['ItemCode'],
        watermarkField: 'LastModified',
        comparedFields: [],
      },
    });
    expect(saved.sourceImpl).toBe('autocount_http');
    expect(saved.sourceConfig.path).toBe('/itembypage');
    const reloaded = await service.getEtlTask('company-http', 'product');
    expect(reloaded.sourceImpl).toBe('autocount_http');
    expect(reloaded.sourceConfig.keyFields).toEqual(['ItemCode']);
  });

  it('the saved task is BORN on the Entities list (regression: bornEntities() used to gate on `query` only, an HTTP task never has one)', async () => {
    const task = await service.getEtlTask('company-http', 'product');
    await service.updateEtlTask('company-http', 'product', {
      sourceImpl: 'autocount_http',
      sourceConfig: {
        ...task.sourceConfig,
        connectionId: 'conn-api-mocha',
        path: '/itembypage',
        keyFields: ['ItemCode'],
        watermarkField: 'LastModified',
      },
    });
    const detail = await service.getCompany('company-http');
    const row = detail.entities.find((e) => e.entityType === 'product');
    expect(row).toBeDefined();
    expect(row!.sourceImpl).toBe('autocount_http');
  });

  it('422s on connectionId when it is not an open (no-auth) connection', async () => {
    const task = await service.getEtlTask('company-http', 'product');
    const err = await rejected(
      service.updateEtlTask('company-http', 'product', {
        sourceImpl: 'autocount_http',
        sourceConfig: { ...task.sourceConfig, connectionId: 'conn-api-vendor', path: '/itembypage' },
      }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { connectionId: expect.any(String) } });
  });

  it('422s on a blank path', async () => {
    const task = await service.getEtlTask('company-http', 'product');
    const err = await rejected(
      service.updateEtlTask('company-http', 'product', {
        sourceImpl: 'autocount_http',
        sourceConfig: { ...task.sourceConfig, connectionId: 'conn-api-mocha', path: '' },
      }),
    );
    expect(err.status).toBe(422);
    expect(err.detail).toEqual({ fieldErrors: { path: expect.any(String) } });
  });

  it('a DB company\'s HTTP task may reference ANY open connection - the DB-lock (AC-01-09) narrows to sql_db only (AC-08-13)', async () => {
    const task = await service.getEtlTask('company-db', 'product_category');
    const saved = await service.updateEtlTask('company-db', 'product_category', {
      sourceImpl: 'autocount_http',
      sourceConfig: {
        ...task.sourceConfig,
        connectionId: 'conn-api-sorento',
        path: '/ItemGroup',
        keyFields: ['ItemGroup'],
      },
    });
    expect(saved.sourceImpl).toBe('autocount_http');
    expect(saved.sourceConfig.connectionId).toBe('conn-api-sorento');
  });

  it('AC-08-28: switching an ACTIVE task\'s impl sets it back to draft', async () => {
    const task = await service.getEtlTask('company-db', 'customer');
    // company-db's `customer` task is seeded ACTIVE (see the DB-company fixture).
    expect(task.etlStatus).toBe('active');
    const saved = await service.updateEtlTask('company-db', 'customer', {
      sourceImpl: 'autocount_http',
      sourceConfig: {
        ...task.sourceConfig,
        connectionId: 'conn-api-sorento',
        path: '/debtorbypage',
        keyFields: ['AccNo'],
      },
    });
    expect(saved.etlStatus).toBe('draft');
  });

  it('re-saving the SAME impl/connection/path leaves an active task active', async () => {
    // Seed an active HTTP task on the open company.
    const task = await service.getEtlTask('company-http', 'brand');
    const first = await service.updateEtlTask('company-http', 'brand', {
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task.sourceConfig, connectionId: 'conn-api-mocha', path: '/ItemBrand', keyFields: ['ItemBrand'] },
    });
    await service.previewEtlTask('company-http', 'brand').catch(() => {});
    // Only exercise the "no unnecessary draft" half here - re-save identical config.
    const second = await service.updateEtlTask('company-http', 'brand', {
      sourceImpl: 'autocount_http',
      sourceConfig: first.sourceConfig,
    });
    expect(second.etlStatus).toBe(first.etlStatus);
  });
});

describe('getMapping - HTTP preset rows (AC-08-16/21) vs the legacy vendor customer view', () => {
  it("a product task's Mapping tab shows the HTTP preset rows (ItemCode->code etc.), never the generic master view", async () => {
    const view = await service.getMapping('company-http', 'product');
    expect(view.rows.map((r) => [r.sourcePath, r.canonicalField])).toEqual([
      ['ItemCode', 'code'],
      ['Description', 'name'],
      ['Desc2', 'description'],
      ['ItemGroup', 'category_code'],
      ['ItemBrand', 'brand_code'],
      ['BaseUOM', 'uom_code'],
      ['IsActive', 'is_active'],
      ['Discontinued', 'is_discontinued'],
    ]);
  });

  it("brand's Mapping tab (a brand-new entity with no vendor equivalent) always reads its HTTP preset", async () => {
    const view = await service.getMapping('company-http', 'brand');
    expect(view.rows.map((r) => r.canonicalField)).toEqual(['code', 'name', 'description']);
  });

  it("customer on the vendor (autocount_read) path keeps the legacy AccNo/CompanyName/IsActive/EmailAddress view", async () => {
    const view = await service.getMapping('company-1', 'customer');
    expect(view.rows.map((r) => r.canonicalField)).toEqual([
      'code',
      'name',
      'is_active',
      'email',
      'last_modified',
    ]);
  });

  it('customer on the open API (autocount_http) path reads its HTTP preset instead', async () => {
    const task = await service.getEtlTask('company-http', 'customer');
    await service.updateEtlTask('company-http', 'customer', {
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task.sourceConfig, connectionId: 'conn-api-mocha', path: '/debtorbypage', keyFields: ['AccNo'] },
    });
    const view = await service.getMapping('company-http', 'customer');
    expect(view.rows.map((r) => r.canonicalField)).toEqual(['code', 'name', 'phone_number', 'is_active']);
  });
});

describe('previewHttp - the task echo only fires for a config that actually exists (review round 8)', () => {
  it('never echoes a task for an entity with no config row at all - no prior getEtlTask/updateEtlTask this session, matching the real backend\'s `task: null`', async () => {
    const preview = await service.previewHttp({
      connectionId: 'conn-api-mocha',
      path: '/itembypage',
      companyId: 'company-http',
      entityType: 'never-touched-entity',
    });
    expect(preview.task).toBeUndefined();
  });

  it('echoes the stamped task once the entity has a real config row', async () => {
    // The real backend only stamps/echoes when `ac_entity_config` already has
    // a row for the pair - `getEtlTask` synthesizes an in-memory draft for a
    // GET, but `updateEtlTask` is what actually persists one.
    const task = await service.getEtlTask('company-http', 'product');
    await service.updateEtlTask('company-http', 'product', {
      sourceImpl: 'autocount_http',
      sourceConfig: { ...task.sourceConfig, connectionId: 'conn-api-mocha', path: '/itembypage', keyFields: ['ItemCode'] },
    });
    const preview = await service.previewHttp({
      connectionId: 'conn-api-mocha',
      path: '/itembypage',
      companyId: 'company-http',
      entityType: 'product',
    });
    expect(preview.task).toBeDefined();
    expect(preview.task!.resultColumns).toEqual(expect.arrayContaining(['ItemCode']));
  });
});
