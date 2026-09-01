import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { IntegrationProvider } from '@/types/integration';

const providers = vi.fn();
const testBucket = vi.fn();
const startMigration = vi.fn();

vi.mock('@/services/integration-service', () => ({
  integrationService: { providers: () => providers() },
}));
vi.mock('@/services/storage-migration-service', () => ({
  storageMigrationService: {
    testBucket: (...a: unknown[]) => testBucket(...a),
    startMigration: (...a: unknown[]) => startMigration(...a),
  },
}));

import { useStorageMigration } from './use-storage-migration';

const S3: IntegrationProvider = {
  provider: 's3',
  type: 'storage',
  title: 'Amazon S3',
  description: 'S3 bucket',
  icon: null,
  fields: [
    { key: 'bucket', label: 'Bucket', type: 'text', required: true },
    { key: 'accessKeyId', label: 'Access key', type: 'password', required: true, secret: true },
  ],
  testLabel: 'Test',
  testTarget: null,
};

const EMAIL: IntegrationProvider = { ...S3, provider: 'smtp', type: 'email', title: 'SMTP' };

beforeEach(() => {
  vi.clearAllMocks();
  providers.mockResolvedValue([S3, EMAIL]);
  testBucket.mockResolvedValue({ ok: true, message: 'Bucket verified.' });
  startMigration.mockResolvedValue({ id: 'job-1', status: 'pending' });
});

describe('useStorageMigration - test-gated Start (AC-10-18)', () => {
  it('lists STORAGE providers only', async () => {
    const { result } = renderHook(() => useStorageMigration(true));
    await waitFor(() => expect(result.current.providers.length).toBe(1));
    expect(result.current.providers[0].provider).toBe('s3');
  });

  it('gates canStart on a passing test AND a matching typed-confirm', async () => {
    const { result } = renderHook(() => useStorageMigration(true));
    await waitFor(() => expect(result.current.providers.length).toBe(1));

    act(() => result.current.onProviderChange('s3'));
    act(() => result.current.form.setValue('config.bucket', 'my-new-bucket'));
    act(() => result.current.form.setValue('credentials.accessKeyId', 'AKIA'));

    // No test yet → cannot start.
    expect(result.current.canStart).toBe(false);

    await act(async () => {
      await result.current.runTest();
    });
    await waitFor(() => expect(result.current.testResult?.ok).toBe(true));

    // Passing test but the typed-confirm doesn't match yet.
    expect(result.current.canStart).toBe(false);

    // Type the exact bucket-connection name to confirm.
    act(() => result.current.setConfirmValue(result.current.targetName));
    await waitFor(() => expect(result.current.canStart).toBe(true));
  });

  it('a FAILING test never enables Start', async () => {
    testBucket.mockResolvedValue({ ok: false, message: 'Access denied.' });
    const { result } = renderHook(() => useStorageMigration(true));
    await waitFor(() => expect(result.current.providers.length).toBe(1));

    act(() => result.current.onProviderChange('s3'));
    act(() => result.current.form.setValue('config.bucket', 'b'));
    act(() => result.current.form.setValue('credentials.accessKeyId', 'k'));
    await act(async () => {
      await result.current.runTest();
    });
    await waitFor(() => expect(result.current.testResult?.ok).toBe(false));

    act(() => result.current.setConfirmValue(result.current.targetName));
    expect(result.current.canStart).toBe(false);
  });

  it('start() calls the service and returns the job when gated open', async () => {
    const { result } = renderHook(() => useStorageMigration(true));
    await waitFor(() => expect(result.current.providers.length).toBe(1));
    act(() => result.current.onProviderChange('s3'));
    act(() => result.current.form.setValue('config.bucket', 'b'));
    act(() => result.current.form.setValue('credentials.accessKeyId', 'k'));
    await act(async () => {
      await result.current.runTest();
    });
    act(() => result.current.setConfirmValue(result.current.targetName));
    await waitFor(() => expect(result.current.canStart).toBe(true));

    let job: unknown;
    await act(async () => {
      job = await result.current.start();
    });
    expect(startMigration).toHaveBeenCalledTimes(1);
    expect((job as { id: string }).id).toBe('job-1');
  });
});
