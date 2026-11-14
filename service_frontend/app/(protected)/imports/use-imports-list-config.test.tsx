/**
 * AC-DLA-56 (T7) - /imports moved onto the Resource shell (a server-
 * paginated list, so DataGrid via ResourceList, not a raw @/components/ui/table).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const { list } = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock('@/services/import-service', () => ({
  importService: { list },
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (iso: string) => `formatted:${iso}` }),
}));

import { useImportsListConfig } from './use-imports-list-config';
import type { ImportJob } from '@/types/import';

function aJob(over: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'j1',
    entityType: 'user',
    mode: 'upsert',
    status: 'done',
    abortOnInvalid: true,
    triggerAutomations: false,
    sheetName: null,
    mapping: null,
    context: null,
    totalRows: 10,
    validRows: 9,
    invalidRows: 1,
    errors: null,
    hasErrorFile: false,
    createdIds: null,
    updatedIds: null,
    filesPurged: false,
    createdAt: '2026-07-18T00:00:00Z',
    finishedAt: null,
    ...over,
  };
}

beforeEach(() => list.mockReset());

describe('useImportsListConfig', () => {
  it('exposes the entity/mode/status/rows/created columns', () => {
    const { result } = renderHook(() => useImportsListConfig());
    const ids = result.current.columns.map((c) => c.id);
    expect(ids).toEqual(['entityType', 'mode', 'status', 'rows', 'created']);
  });

  it('rowHref opens the job detail route', () => {
    const { result } = renderHook(() => useImportsListConfig());
    expect(result.current.rowHref?.(aJob({ id: 'abc' }))).toBe('/imports/abc');
  });

  it('the fetcher passes page/pageSize through to importService.list and maps the result to ListResult', async () => {
    list.mockResolvedValue({ items: [aJob()], total: 42, page: 2, pageSize: 25 });
    const { result } = renderHook(() => useImportsListConfig());
    const out = await result.current.fetcher({ page: 2, pageSize: 25, search: '', sort: null, filter: null });
    expect(list).toHaveBeenCalledWith({ page: 2, pageSize: 25 });
    expect(out).toEqual({ data: [aJob()], total: 42, page: 2 });
  });

  it('has no server-side status views (segments are not wired for this list)', () => {
    const { result } = renderHook(() => useImportsListConfig());
    expect(result.current.enableStatusViews).toBe(false);
  });
});
