import { describe, expect, it } from 'vitest';

import {
  connectionFormSchema,
  defaultsForProvider,
  dependentDefault,
  isFieldVisible,
  requiredFieldErrors,
  storedOrEffective,
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

describe('storedOrEffective (read mode and edit prefill share one resolution)', () => {
  const version = sorento.fields.find((f) => f.key === 'sorentoContractVersion') as ProviderField;
  const baseUrl = sorento.fields.find((f) => f.key === 'baseUrl') as ProviderField;

  it('a legacy connection reads "1" for the contract version, never blank', () => {
    expect(storedOrEffective(version, { baseUrl: 'https://s' })).toBe('1');
    expect(version.options?.find((o) => o.value === storedOrEffective(version, {}))?.label).toBe(
      '1 (legacy)',
    );
  });

  it('a stored value wins, and other fields stay blank when missing', () => {
    expect(storedOrEffective(version, { sorentoContractVersion: '2' })).toBe('2');
    expect(storedOrEffective(baseUrl, {})).toBe('');
  });
});

// feat/sink-concurrency-ui: a SECOND effective-value field on the Sorento
// connection. The per-key hardcode for the contract version does not scale;
// the provider payload carries the effective (platform-default) value on the
// field itself and `storedOrEffective` falls back to it generically.
describe('Sorento sink concurrency read-mode / edit prefill (feat/sink-concurrency-ui)', () => {
  const sinkConcurrency: ProviderField = {
    key: 'sinkConcurrency',
    label: 'Push concurrency',
    type: 'select',
    required: false,
    effectiveValue: '1',
    options: [
      { value: '1', label: '1 (sequential)' },
      { value: '2', label: '2' },
      { value: '3', label: '3' },
      { value: '4', label: '4' },
    ],
  };
  const sorentoWithConcurrency: IntegrationProvider = {
    ...sorento,
    fields: [sorento.fields[0], sorento.fields[1], sinkConcurrency, sorento.fields[2]],
  };

  it('an unset value shows the EFFECTIVE platform default the field carries', () => {
    expect(storedOrEffective(sinkConcurrency, { baseUrl: 'https://sorento.example.com' })).toBe('1');
    const values = valuesForConnection(sorentoWithConcurrency, {
      provider: 'sorento',
      name: 'Sorento',
      config: { baseUrl: 'https://sorento.example.com', sorentoContractVersion: '2' },
    });
    expect(values.config.sinkConcurrency).toBe('1');
  });

  it('a stored "2" wins over the effective value', () => {
    expect(
      storedOrEffective(sinkConcurrency, { baseUrl: 'https://sorento.example.com', sinkConcurrency: '2' }),
    ).toBe('2');
  });

  it('the contract-version behaviour is unchanged by the generic fallback', () => {
    const values = valuesForConnection(sorentoWithConcurrency, {
      provider: 'sorento',
      name: 'Sorento',
      config: { baseUrl: 'https://sorento.example.com' },
    });
    expect(values.config.sorentoContractVersion).toBe('1');
  });
});

// sprint-5/08 D11 (AC-08-01/04) - the generic `showWhen` mechanism, fabricated
// on a fixture provider ahead of the real `autocount` `auth` field (S2
// backend). Provider-agnostic on purpose: it must work for ANY future
// conditional field, not just this one.
describe('showWhen (plan sprint-5/08, D11/AC-08-01/04)', () => {
  const openApi: IntegrationProvider = {
    provider: 'fixture-open-api',
    type: 'erp',
    title: 'Fixture open API',
    description: '',
    icon: null,
    testLabel: 'Test',
    testTarget: null,
    fields: [
      {
        key: 'auth',
        label: 'Auth',
        type: 'select',
        required: true,
        defaultValue: 'basic',
        options: [
          { value: 'basic', label: 'Basic auth' },
          { value: 'none', label: 'No auth' },
        ],
      },
      { key: 'baseUrl', label: 'Base URL', type: 'text', required: true },
      {
        key: 'appId',
        label: 'AppId',
        type: 'text',
        required: true,
        showWhen: { field: 'auth', values: ['basic'] },
      },
      {
        key: 'password',
        label: 'Password',
        type: 'password',
        required: true,
        secret: true,
        showWhen: { field: 'auth', values: ['basic'] },
      },
    ],
  };
  const appId = openApi.fields.find((f) => f.key === 'appId')!;
  const baseUrl = openApi.fields.find((f) => f.key === 'baseUrl')!;

  it('isFieldVisible: absent showWhen is always visible; a matching driver value is visible', () => {
    expect(isFieldVisible(baseUrl, { auth: 'none' })).toBe(true);
    expect(isFieldVisible(appId, { auth: 'basic' })).toBe(true);
  });

  it('isFieldVisible: a non-matching (or missing) driver value is hidden', () => {
    expect(isFieldVisible(appId, { auth: 'none' })).toBe(false);
    expect(isFieldVisible(appId, {})).toBe(false);
  });

  it('requiredFieldErrors drops a hidden required field entirely', () => {
    const values = defaultsForProvider(openApi);
    values.config.auth = 'none';
    values.config.baseUrl = 'https://hapi.example/api/db1';
    const errors = requiredFieldErrors(openApi, values, true);
    expect(errors.map((e) => e.path)).not.toContain('config.appId');
    expect(errors.map((e) => e.path)).not.toContain('credentials.password');
  });

  it('requiredFieldErrors still requires a hidden field\'s driver-matching sibling', () => {
    const values = defaultsForProvider(openApi);
    values.config.auth = 'basic';
    values.config.baseUrl = 'https://hapi.example/api/db1';
    const errors = requiredFieldErrors(openApi, values, true);
    expect(errors.map((e) => e.path)).toEqual(
      expect.arrayContaining(['config.appId', 'credentials.password']),
    );
  });

  it('toConnectionInput drops a hidden field from BOTH config and credentials', () => {
    const values = defaultsForProvider(openApi);
    values.config.auth = 'none';
    values.config.baseUrl = 'https://hapi.example/api/db1';
    // A stale AppId/password left over from switching Auth to "none" -
    // must never reach the wire even though the RHF values still carry it.
    values.config.appId = 'STALE';
    values.credentials.password = 'stale-secret';
    const input = toConnectionInput(values, openApi);
    expect(input.config).toEqual({ auth: 'none', baseUrl: 'https://hapi.example/api/db1' });
    expect(input.credentials).toEqual({});
  });

  it('toConnectionInput keeps every field when the provider is omitted (back-compat)', () => {
    const values = defaultsForProvider(openApi);
    values.config.auth = 'none';
    values.config.appId = 'STALE';
    const input = toConnectionInput(values);
    expect(input.config.appId).toBe('STALE');
  });

  it('toConnectionInput sends a visible field normally', () => {
    const values = defaultsForProvider(openApi);
    values.config.auth = 'basic';
    values.config.appId = 'HQ01';
    values.credentials.password = 'secret';
    const input = toConnectionInput(values, openApi);
    expect(input.config.appId).toBe('HQ01');
    expect(input.credentials.password).toBe('secret');
  });
});
