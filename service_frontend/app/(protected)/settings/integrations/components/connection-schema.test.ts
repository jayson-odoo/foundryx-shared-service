import { describe, expect, it } from 'vitest';

import {
  connectionFormSchema,
  defaultsForProvider,
  dependentDefault,
  requiredFieldErrors,
  toConnectionInput,
  valuesForConnection,
} from './connection-schema';
import { SQL_DATABASE_PROVIDER } from '@/services/integration-service.mock';
import type { IntegrationProvider, ProviderField } from '@/types/integration';

describe('SQL-database provider on the registry form (plan 22, AC-22-04)', () => {
  const port = SQL_DATABASE_PROVIDER.fields.find((f) => f.key === 'port') as ProviderField;

  it('declares dbType as a select of the three dialects and password as a secret', () => {
    const dbType = SQL_DATABASE_PROVIDER.fields.find((f) => f.key === 'dbType');
    expect(dbType?.type).toBe('select');
    expect(dbType?.options?.map((o) => o.value)).toEqual(['mssql', 'postgresql', 'mysql']);
    expect(SQL_DATABASE_PROVIDER.fields.find((f) => f.key === 'password')?.secret).toBe(true);
    expect(SQL_DATABASE_PROVIDER.fields.map((f) => f.key)).toEqual([
      'dbType',
      'host',
      'port',
      'database',
      'username',
      'password',
    ]);
  });

  it('defaults to MSSQL + 1433 and validates as form values', () => {
    const values = defaultsForProvider(SQL_DATABASE_PROVIDER);
    expect(values.config).toMatchObject({ dbType: 'mssql', port: '1433' });
    expect(values.credentials).toEqual({ password: '' });
    expect(connectionFormSchema.safeParse(values).success).toBe(true);
  });

  it('port follows the dialect while it still holds a stock default', () => {
    expect(dependentDefault(port, 'postgresql', '1433')).toBe('5432');
    expect(dependentDefault(port, 'mysql', '')).toBe('3306');
    expect(dependentDefault(port, 'mssql', '5432')).toBe('1433');
  });

  it('never clobbers an operator-typed port, and is a no-op when unchanged', () => {
    expect(dependentDefault(port, 'postgresql', '15432')).toBeNull();
    expect(dependentDefault(port, 'mssql', '1433')).toBeNull();
    expect(dependentDefault(port, 'oracle', '1433')).toBeNull();
    const host = SQL_DATABASE_PROVIDER.fields.find((f) => f.key === 'host') as ProviderField;
    expect(dependentDefault(host, 'postgresql', '')).toBeNull();
  });
});

const r2: IntegrationProvider = {
  provider: 'r2',
  type: 'storage',
  title: 'Cloudflare R2',
  description: '',
  icon: 'cloud',
  testLabel: 'Verify storage',
  testTarget: null,
  fields: [
    { key: 'accountId', label: 'Account ID', type: 'text', required: true },
    { key: 'bucket', label: 'Bucket', type: 'text', required: true },
    { key: 'accessKeyId', label: 'Access key ID', type: 'password', required: true, secret: true },
    {
      key: 'secretAccessKey',
      label: 'Secret access key',
      type: 'password',
      required: true,
      secret: true,
    },
    { key: 'cdnBaseUrl', label: 'CDN base URL', type: 'text', required: false, advanced: true },
  ],
};

const connection = {
  provider: 'r2',
  name: 'Cloudflare R2',
  config: { accountId: 'acc', bucket: 'b', cdnBaseUrl: 'https://cdn.example.com' },
};

describe('connection-schema (blank-to-keep contract, plan 06 D6)', () => {
  it('prefills secrets as empty strings - undefined fails z.record with a bare "Required"', () => {
    const values = valuesForConnection(r2, connection);
    expect(values.credentials).toEqual({ accessKeyId: '', secretAccessKey: '' });
    // The zod shape must accept the prefilled edit values as-is.
    expect(connectionFormSchema.safeParse(values).success).toBe(true);
  });

  it('defaultsForProvider seeds secret keys too', () => {
    const values = defaultsForProvider(r2);
    expect(values.credentials).toEqual({ accessKeyId: '', secretAccessKey: '' });
    expect(connectionFormSchema.safeParse(values).success).toBe(true);
  });

  it('edit: blank secrets raise NO required errors (keep stored)', () => {
    const values = valuesForConnection(r2, connection);
    expect(requiredFieldErrors(r2, values, false)).toEqual([]);
  });

  it('create: blank secrets DO raise required errors', () => {
    const values = defaultsForProvider(r2);
    values.config.accountId = 'acc';
    values.config.bucket = 'b';
    const errors = requiredFieldErrors(r2, values, true);
    expect(errors.map((e) => e.path)).toEqual([
      'credentials.accessKeyId',
      'credentials.secretAccessKey',
    ]);
  });

  it('payload strips blank secrets so the API keeps stored values', () => {
    const values = valuesForConnection(r2, connection);
    values.credentials.accessKeyId = '  ';
    expect(toConnectionInput(values).credentials).toEqual({});
  });
});

const sorento: IntegrationProvider = {
  provider: 'sorento',
  type: 'consumer',
  title: 'Sorento',
  description: '',
  icon: 'upload-cloud',
  testLabel: 'Test connection',
  testTarget: null,
  fields: [
    { key: 'baseUrl', label: 'Sorento base URL', type: 'text', required: true },
    {
      key: 'sorentoContractVersion',
      label: 'Contract version',
      type: 'select',
      required: true,
      defaultValue: '2',
      options: [
        { value: '1', label: '1 (legacy)' },
        { value: '2', label: '2' },
      ],
    },
    { key: 'apiKey', label: 'API key', type: 'password', required: true, secret: true },
  ],
};

describe('Sorento contract version on edit (fix/sorento-contract-version-field)', () => {
  it('a connection saved before the field existed prefills the EFFECTIVE "1", not blank', () => {
    const values = valuesForConnection(sorento, {
      provider: 'sorento',
      name: 'Sorento',
      config: { baseUrl: 'https://sorento.example.com' },
    });
    expect(values.config).toEqual({
      baseUrl: 'https://sorento.example.com',
      sorentoContractVersion: '1',
    });
    // The prefilled value satisfies the required check, so an unrelated
    // save of the connection is not blocked by a field the operator never set.
    expect(requiredFieldErrors(sorento, values, false)).toEqual([]);
    expect(connectionFormSchema.safeParse(values).success).toBe(true);
  });

  it('a stored "2" wins over the effective fallback', () => {
    const values = valuesForConnection(sorento, {
      provider: 'sorento',
      name: 'Sorento',
      config: { baseUrl: 'https://sorento.example.com', sorentoContractVersion: '2' },
    });
    expect(values.config.sorentoContractVersion).toBe('2');
  });

  it('a fresh Sorento connection still defaults the select to "2"', () => {
    expect(defaultsForProvider(sorento).config.sorentoContractVersion).toBe('2');
  });

  it('the fallback is scoped to that key - other missing fields stay blank', () => {
    const values = valuesForConnection(r2, { provider: 'r2', name: 'R2', config: { bucket: 'b' } });
    expect(values.config).toEqual({ accountId: '', bucket: 'b', cdnBaseUrl: '' });
  });
});
