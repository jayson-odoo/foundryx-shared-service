/**
 * The owner's "Joined = Today" finding: the list sent the picked days as
 * `['2026-11-19', '2026-11-19']`, which the API reads as one UTC midnight, so
 * nothing matched. The list now asks the server with the user's local day as
 * instants (both looks share this hook); its own state keeps the days.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useResourceList } from './use-resource-list';
import type { FilterFieldDef, FilterGroup, ListQuery, ListResult } from '@/types/resource';

interface Row {
  id: string;
}

vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));

const FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'joined', label: 'Joined', type: 'date' },
];

const today: FilterGroup = {
  kind: 'group',
  combinator: 'and',
  rules: [{ kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-19', '2026-11-19'] }],
};

describe('useResourceList day filters', () => {
  it('asks the server for the whole local day and keeps the days in its own state', async () => {
    const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Row>>>(async () => ({ data: [], total: 0, page: 0 }));
    const { result } = renderHook(() =>
      useResourceList<Row>({ fetcher, filterFields: FIELDS, timeZone: 'Asia/Kuala_Lumpur' }),
    );
    act(() => result.current.setFilter(today));

    await waitFor(() => expect(fetcher.mock.calls.at(-1)?.[0].filter).not.toBeNull());
    expect(fetcher.mock.calls.at(-1)?.[0].filter?.rules[0]).toEqual({
      kind: 'condition',
      field: 'joined',
      operator: 'between',
      value: ['2026-11-18T16:00:00.000Z', '2026-11-19T15:59:59.999Z'],
    });
    expect(result.current.serverQuery.filter?.rules[0]).toEqual(fetcher.mock.calls.at(-1)?.[0].filter?.rules[0]);
    // The address, saved segments and the pickers still read days.
    expect(result.current.query.filter).toBe(today);
    expect(result.current.filter).toBe(today);
  });

  it('does not fetch again when the same fields come in a new array each render', async () => {
    const fetcher = vi.fn(async (): Promise<ListResult<Row>> => ({ data: [], total: 0, page: 0 }));
    const { rerender } = renderHook(() =>
      useResourceList<Row>({ fetcher, filterFields: [...FIELDS], timeZone: 'Asia/Kuala_Lumpur' }),
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    rerender();
    rerender();
    await new Promise((r) => setTimeout(r, 20));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('without fields or a zone sends the filter as held (unchanged for other callers)', async () => {
    const fetcher = vi.fn<(q: ListQuery) => Promise<ListResult<Row>>>(async () => ({ data: [], total: 0, page: 0 }));
    const { result } = renderHook(() => useResourceList<Row>({ fetcher }));
    act(() => result.current.setFilter(today));
    await waitFor(() => expect(fetcher.mock.calls.at(-1)?.[0].filter).toBe(today));
  });
});
