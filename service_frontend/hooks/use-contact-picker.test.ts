/**
 * Server-searched contact picker (review round 1, S2) - `useContactPicker`
 * replaces the S0-era `conversationService.listThreads` stand-in (capped at
 * 50 rows, no search) with a debounced `contactService.list` search that
 * still lets an already-selected contact keep its label across a later,
 * differently-filtered query.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContactListItem } from '@/types/omnichannel';

const list = vi.fn();
const get = vi.fn();
vi.mock('@/services/contact-service', () => ({
  contactService: {
    list: (...args: unknown[]) => list(...args),
    get: (...args: unknown[]) => get(...args),
  },
}));

import { useContactPicker } from './use-contact-picker';

function contact(id: string, name: string, phone = '+60 12-000 0000'): ContactListItem {
  return { id, name, phone } as ContactListItem;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useContactPicker', () => {
  it('fetches an initial page (empty search) for a workspace', async () => {
    list.mockResolvedValue({ data: [contact('cnt-1', 'Alex Tan')], total: 1, page: 0 });
    const { result } = renderHook(() => useContactPicker('ws-1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(list).toHaveBeenCalledWith('ws-1', { page: 0, pageSize: 50, search: undefined });
    expect(result.current.options).toEqual([{ label: 'Alex Tan (+60 12-000 0000)', value: 'cnt-1' }]);
  });

  it('debounces the typed query before searching', async () => {
    list.mockResolvedValue({ data: [], total: 0, page: 0 });
    const { result } = renderHook(() => useContactPicker('ws-1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    list.mockClear();

    act(() => result.current.setQuery('a'));
    act(() => result.current.setQuery('al'));
    act(() => result.current.setQuery('ale'));
    expect(list).not.toHaveBeenCalled(); // debounce window still open

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith('ws-1', { page: 0, pageSize: 50, search: 'ale' });
  });

  it('keeps an already-selected contact resolvable after a later, non-matching search', async () => {
    list.mockResolvedValueOnce({ data: [contact('cnt-1', 'Alex Tan')], total: 1, page: 0 });
    const { result, rerender } = renderHook(
      ({ selected }: { selected: string[] }) => useContactPicker('ws-1', selected),
      { initialProps: { selected: [] as string[] } },
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    // A later search that does NOT return cnt-1 (e.g. a different name typed).
    list.mockResolvedValueOnce({ data: [contact('cnt-2', 'Bee Two')], total: 1, page: 0 });
    act(() => result.current.setQuery('bee'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.options.map((o) => o.value)).toEqual(['cnt-1', 'cnt-2']);

    // The caller marks cnt-1 as selected (it was already known - no extra fetch).
    rerender({ selected: ['cnt-1'] });
    expect(get).not.toHaveBeenCalled();
    expect(result.current.options.some((o) => o.value === 'cnt-1' && o.label.includes('Alex Tan'))).toBe(true);
  });

  it('resolves a selected id NOT yet seen by any search via a direct get()', async () => {
    list.mockResolvedValue({ data: [], total: 0, page: 0 });
    get.mockResolvedValue(contact('cnt-9', 'Nine Contact'));
    const { result } = renderHook(() => useContactPicker('ws-1', ['cnt-9']));

    // The missing-selected-id resolution fires with no debounce - just flush
    // the pending microtasks (no fake-timer advance needed).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(get).toHaveBeenCalledWith('ws-1', 'cnt-9');
    expect(result.current.options.some((o) => o.value === 'cnt-9')).toBe(true);
  });

  it('post-approval N2: caps the per-pass selected-id backfill instead of firing one GET per id unbounded', async () => {
    list.mockResolvedValue({ data: [], total: 0, page: 0 });
    get.mockImplementation((_ws: string, id: string) => Promise.resolve(contact(id, `Contact ${id}`)));
    const manyIds = Array.from({ length: 30 }, (_, i) => `cnt-${i}`);
    renderHook(() => useContactPicker('ws-1', manyIds));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // Capped at 20 per pass, NOT one call per all 30 selected ids.
    expect(get).toHaveBeenCalledTimes(20);
  });

  it('does nothing without a workspaceId', async () => {
    const { result } = renderHook(() => useContactPicker(null));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(list).not.toHaveBeenCalled();
    expect(result.current.options).toEqual([]);
  });
});
