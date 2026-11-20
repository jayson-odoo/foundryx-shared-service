import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import {
  MOCK_REDATED_DOC_NO,
  mockAutocountDocLookupService,
  resetMockDocLookup,
} from '@/services/autocount-doc-lookup-service.mock';
import type { AutocountDocLookupService } from '@/services/autocount-doc-lookup-service';
import type { DocLookupJob } from '@/types/autocount-doc-lookup';
import { lookupErrorMessage, useDocLookup, useDocLookupTypes } from './use-autocount-doc-lookup';

const fast = () => 1;

beforeEach(() => resetMockDocLookup());

describe('useDocLookup', () => {
  it('shows stored sightings, then the finished live result', async () => {
    const { result } = renderHook(() =>
      useDocLookup({ service: mockAutocountDocLookupService, pollDelay: fast }),
    );
    await act(async () => {
      await result.current.search({ companyId: 'c1', docNo: MOCK_REDATED_DOC_NO, docType: 'delivery_order' });
    });
    expect(result.current.phase).toBe('done');
    expect(result.current.stored?.snapshots).toHaveLength(1);
    expect(result.current.job?.result?.redated).toEqual({ from: '2026-10-01', to: '2026-10-05', source: 'snapshot' });
  });

  it('polls a running job until it ends', async () => {
    const running: DocLookupJob = {
      jobId: 'j1', status: 'running', companyId: 'c1', docNo: 'X', docType: 'delivery_order',
      progressDone: 1, progressTotal: 3, result: null, error: null, createdAt: null, finishedAt: null,
    };
    const getJob = vi
      .fn<AutocountDocLookupService['getJob']>()
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce({ ...running, status: 'done', progressDone: 3 });
    const service: AutocountDocLookupService = {
      ...mockAutocountDocLookupService,
      start: vi.fn().mockResolvedValue(running),
      getJob,
    };
    const { result } = renderHook(() => useDocLookup({ service, pollDelay: fast }));
    await act(async () => {
      await result.current.search({ companyId: 'c1', docNo: 'X' });
    });
    expect(getJob).toHaveBeenCalledTimes(2);
    expect(result.current.phase).toBe('done');
    expect(result.current.job?.status).toBe('done');
  });

  it('surfaces the backend detail message on a refused start', async () => {
    const service: AutocountDocLookupService = {
      ...mockAutocountDocLookupService,
      start: vi.fn().mockRejectedValue(
        new ApiError('Request failed', 409, null, {
          code: 'NO_CONNECTION',
          message: 'This company has no AutoCount connection for delivery orders.',
        }),
      ),
    };
    const { result } = renderHook(() => useDocLookup({ service, pollDelay: fast }));
    await act(async () => {
      await result.current.search({ companyId: 'c1', docNo: 'X' });
    });
    expect(result.current.phase).toBe('error');
    expect(result.current.error).toBe('This company has no AutoCount connection for delivery orders.');
  });

  it('stops a running job', async () => {
    const running: DocLookupJob = {
      jobId: 'j2', status: 'running', companyId: 'c1', docNo: 'X', docType: 'delivery_order',
      progressDone: 0, progressTotal: 3, result: null, error: null, createdAt: null, finishedAt: null,
    };
    let status: DocLookupJob['status'] = 'running';
    const stop = vi.fn().mockImplementation(async () => {
      status = 'aborted';
      return { ...running, status };
    });
    const service: AutocountDocLookupService = {
      ...mockAutocountDocLookupService,
      start: vi.fn().mockResolvedValue(running),
      getJob: vi.fn().mockImplementation(async () => ({ ...running, status })),
      stop,
    };
    const { result } = renderHook(() => useDocLookup({ service, pollDelay: () => 20 }));
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.search({ companyId: 'c1', docNo: 'X' });
    });
    await waitFor(() => expect(result.current.phase).toBe('searching'));
    await act(async () => {
      await result.current.stop();
    });
    await act(async () => {
      await pending;
    });
    expect(stop).toHaveBeenCalledWith('j2');
    expect(result.current.job?.status).toBe('aborted');
    expect(result.current.phase).toBe('done');
  });
});

describe('useDocLookup - review round 1', () => {
  it('names the blocking search on a 409 and can stop it', async () => {
    const stop = vi.fn().mockResolvedValue({});
    const service: AutocountDocLookupService = {
      ...mockAutocountDocLookupService,
      start: vi.fn().mockRejectedValue(
        new ApiError('Request failed', 409, null, {
          code: 'LOOKUP_IN_FLIGHT', message: 'Another document search is running for this company.', jobId: 'jb',
        }),
      ),
      stop,
    };
    const { result } = renderHook(() => useDocLookup({ service, pollDelay: fast }));
    await act(async () => {
      await result.current.search({ companyId: 'c1', docNo: 'X' });
    });
    expect(result.current.blockingJob).toBe('jb');
    await act(async () => {
      await result.current.stopBlocking();
    });
    expect(stop).toHaveBeenCalledWith('jb');
    expect(result.current.phase).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('retries one failed poll before giving up', async () => {
    const running: DocLookupJob = {
      jobId: 'j3', status: 'running', companyId: 'c1', docNo: 'X', docType: 'delivery_order',
      progressDone: 0, progressTotal: 1, result: null, error: null, createdAt: null, finishedAt: null,
    };
    const getJob = vi
      .fn<AutocountDocLookupService['getJob']>()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ ...running, status: 'done' });
    const service: AutocountDocLookupService = {
      ...mockAutocountDocLookupService,
      start: vi.fn().mockResolvedValue(running),
      getJob,
    };
    const { result } = renderHook(() => useDocLookup({ service, pollDelay: fast }));
    await act(async () => {
      await result.current.search({ companyId: 'c1', docNo: 'X' });
    });
    expect(result.current.phase).toBe('done');
    expect(getJob).toHaveBeenCalledTimes(2);
  });
});

describe('useDocLookupTypes', () => {
  it('reports connection per type once a company is chosen', async () => {
    const { result } = renderHook(() => useDocLookupTypes('c1', mockAutocountDocLookupService));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.types.find((t) => t.key === 'goods_receive_note')?.connected).toBe(false);
  });
});

describe('lookupErrorMessage', () => {
  it('falls back to the error message', () => {
    expect(lookupErrorMessage(new Error('boom'))).toBe('boom');
  });
});
