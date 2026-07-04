import { describe, expect, it } from 'vitest';

import {
  connectionFormSchema,
  defaultsForProvider,
  requiredFieldErrors,
  toConnectionInput,
  valuesForConnection,
} from './connection-schema';
import type { IntegrationProvider } from '@/types/integration';

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
  it('prefills secrets as empty strings — undefined fails z.record with a bare "Required"', () => {
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
