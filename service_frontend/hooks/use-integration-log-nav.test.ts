import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const svc = { list: vi.fn() };
vi.mock('@/services/integration-log-service', () => ({
  get integrationLogService() {
    return svc;
  },
}));

import { useIntegrationLogNav } from './use-integration-log-nav';

function result(ids: string[]) {
  return { data: ids.map((id) => ({ id })), total: ids.length, page: 0 };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useIntegrationLogNav (circular record-nav)', () => {
  it('wraps circularly around the middle of the ordered id list', async () => {
    svc.list.mockResolvedValue(result(['a', 'b', 'c']));
    const { result: r } = renderHook(() => useIntegrationLogNav('b'));
    await waitFor(() => expect(r.current.total).toBe(3));
    expect(r.current.index).toBe(1);
    expect(r.current.prevId).toBe('a');
    expect(r.current.nextId).toBe('c');
  });

  it('wraps first→last and last→first', async () => {
    svc.list.mockResolvedValue(result(['a', 'b', 'c']));
    const { result: first } = renderHook(() => useIntegrationLogNav('a'));
    await waitFor(() => expect(first.current.total).toBe(3));
    expect(first.current.prevId).toBe('c'); // wrap to last
    expect(first.current.nextId).toBe('b');

    const { result: last } = renderHook(() => useIntegrationLogNav('c'));
    await waitFor(() => expect(last.current.total).toBe(3));
    expect(last.current.prevId).toBe('b');
    expect(last.current.nextId).toBe('a'); // wrap to first
  });

  it('offers no neighbours for a single-row list', async () => {
    svc.list.mockResolvedValue(result(['only']));
    const { result: r } = renderHook(() => useIntegrationLogNav('only'));
    await waitFor(() => expect(r.current.total).toBe(1));
    expect(r.current.prevId).toBeNull();
    expect(r.current.nextId).toBeNull();
  });

  it('returns index -1 when the current id is outside the fetched window', async () => {
    svc.list.mockResolvedValue(result(['a', 'b']));
    const { result: r } = renderHook(() => useIntegrationLogNav('zzz'));
    await waitFor(() => expect(r.current.total).toBe(2));
    expect(r.current.index).toBe(-1);
    expect(r.current.prevId).toBeNull();
  });

  it('requests the first page at the endpoint cap (200)', async () => {
    svc.list.mockResolvedValue(result(['a']));
    renderHook(() => useIntegrationLogNav('a'));
    await waitFor(() => expect(svc.list).toHaveBeenCalled());
    expect(svc.list).toHaveBeenCalledWith({ page: 0, pageSize: 200 });
  });
});
