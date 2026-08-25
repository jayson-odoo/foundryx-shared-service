import { beforeEach, describe, expect, it } from 'vitest';
import type { ConnectionInput } from '@/types/integration';
import {
  __resetIntegrationMock,
  mockIntegrationService as svc,
} from './integration-service.mock';

const S3_INPUT: ConnectionInput = {
  provider: 's3',
  name: 'Company bucket',
  config: { bucket: 'assets', region: 'ap-southeast-1', cdnBaseUrl: '', endpointUrl: '' },
  credentials: { accessKeyId: 'AKIA…', secretAccessKey: 'shh' },
};

const QUERY = { page: 0, pageSize: 10 };

beforeEach(() => {
  __resetIntegrationMock();
});

describe('provider catalog (plan 06 D2)', () => {
  it('exposes smtp + the two storage cards', async () => {
    const providers = await svc.providers();
    expect(providers.map((p) => p.provider)).toEqual(['smtp', 's3', 'r2']);
    expect(providers.filter((p) => p.type === 'storage')).toHaveLength(2);
  });

  it('r2 asks for an Account ID instead of region/endpoint (derived)', async () => {
    const providers = await svc.providers();
    const r2 = providers.find((p) => p.provider === 'r2')!;
    const keys = r2.fields.map((f) => f.key);
    expect(keys).toContain('accountId');
    expect(keys).not.toContain('region');
    expect(keys).not.toContain('endpointUrl');
  });

  it('both storage cards carry the optional cdnBaseUrl (plan 06 D3)', async () => {
    const providers = await svc.providers();
    for (const key of ['s3', 'r2']) {
      const p = providers.find((x) => x.provider === key)!;
      const cdn = p.fields.find((f) => f.key === 'cdnBaseUrl');
      expect(cdn).toBeDefined();
      expect(cdn!.required).toBe(false);
    }
  });
});

describe('one connection per type (plan 06 D7)', () => {
  it('rejects a second STORAGE connection while one exists', async () => {
    await svc.create(S3_INPUT);
    await expect(
      svc.create({
        provider: 'r2',
        name: 'R2 bucket',
        config: { accountId: 'abc', bucket: 'assets', cdnBaseUrl: '' },
        credentials: { accessKeyId: 'k', secretAccessKey: 's' },
      }),
    ).rejects.toThrow(/already exists - disconnect it first/i);
  });

  it('allows different types side by side', async () => {
    await svc.create(S3_INPUT);
    await expect(
      svc.create({
        provider: 'smtp',
        name: 'Mail',
        config: { host: 'smtp.x.com', port: '587', security: 'starttls', fromEmail: 'a@x.com' },
        credentials: {},
      }),
    ).resolves.toMatchObject({ type: 'email' });
  });

  it('allows reconnecting after a disconnect', async () => {
    const created = await svc.create(S3_INPUT);
    await svc.remove(created.id);
    await expect(svc.create(S3_INPUT)).resolves.toMatchObject({ provider: 's3' });
  });
});

describe('Resource list contract (plan 06 D6)', () => {
  it('lists with search + pagination semantics', async () => {
    await svc.create(S3_INPUT);
    const page = await svc.list({ ...QUERY, search: 'bucket' });
    expect(page.total).toBe(1);
    expect(page.data[0].name).toBe('Company bucket');
    const miss = await svc.list({ ...QUERY, search: 'nothing-matches' });
    expect(miss.total).toBe(0);
  });

  it('getAt resolves the record-nav index', async () => {
    const created = await svc.create(S3_INPUT);
    const at = await svc.getAt(QUERY, 0);
    expect(at.connection?.id).toBe(created.id);
    expect(at.total).toBe(1);
  });

  it('exports CSV with header labels', async () => {
    await svc.create(S3_INPUT);
    const csv = await svc.exportCsv(QUERY, ['name', 'provider', 'status']);
    const [header, row] = csv.split('\n');
    expect(header).toBe('"Name","Provider","Status"');
    expect(row).toContain('"Company bucket"');
    expect(row).toContain('"Amazon S3"');
    expect(row).toContain('"UNVERIFIED"');
  });
});

describe('credentials stay write-only', () => {
  it('never echoes secrets on any read', async () => {
    const created = await svc.create(S3_INPUT);
    const fetched = await svc.get(created.id);
    const listed = await svc.list(QUERY);
    for (const c of [created, fetched, ...listed.data]) {
      expect(JSON.stringify(c)).not.toContain('shh');
    }
  });

  it('blank credentials on update keep the stored secret (test still passes)', async () => {
    const created = await svc.create(S3_INPUT);
    await svc.update(created.id, { name: 'Renamed', credentials: {} });
    // The wrong-secret knob proves which secret is in force:
    const ok = await svc.test(created.id);
    expect(ok.ok).toBe(true);
    await svc.update(created.id, { credentials: { secretAccessKey: 'wrong-secret' } });
    const bad = await svc.test(created.id);
    expect(bad.ok).toBe(false);
    expect(bad.message).toMatch(/SignatureDoesNotMatch/);
  });
});

describe('test semantics', () => {
  it('storage check mentions the CDN probe when cdnBaseUrl is set (plan 06 D3)', async () => {
    const withCdn = await svc.create({
      ...S3_INPUT,
      config: { ...S3_INPUT.config, cdnBaseUrl: 'https://cdn.acme.com' },
    });
    const result = await svc.test(withCdn.id);
    expect(result.ok).toBe(true);
    expect(result.message).toContain('https://cdn.acme.com');
  });

  it('a passing test flips UNVERIFIED → ACTIVE; a failing one → ERROR + lastError', async () => {
    const created = await svc.create(S3_INPUT);
    expect(created.status).toBe('UNVERIFIED');
    await svc.test(created.id);
    expect((await svc.get(created.id)).status).toBe('ACTIVE');
    await svc.update(created.id, { credentials: { secretAccessKey: 'wrong-secret' } });
    await svc.test(created.id);
    const after = await svc.get(created.id);
    expect(after.status).toBe('ERROR');
    expect(after.lastError).toMatch(/403/);
  });
});
