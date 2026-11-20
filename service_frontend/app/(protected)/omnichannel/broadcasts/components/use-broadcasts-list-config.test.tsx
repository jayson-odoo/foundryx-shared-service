/**
 * Broadcasts list column config (tester defect D-1, plan 29 review round 1) -
 * the list had NO `id: 'actions'` column at all, so `useBroadcastActions`'s
 * `surfaces: {row: true}` entries (Edit/Send/Cancel/Duplicate/Delete) were
 * unreachable from a list row (AC-BRD-11, AC-BRD-54's "cancel from the list
 * row action" clause). Mirrors `use-users-list-config.tsx`'s trailing
 * actions column exactly (same size/meta/enable* flags).
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useBroadcastsListConfig } from './use-broadcasts-list-config';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (v: string) => v, formatDate: (v: string) => v }),
}));

vi.mock('@/services/broadcast-service', () => ({
  broadcastService: {
    list: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }),
    cancel: vi.fn(),
    duplicate: vi.fn(),
    send: vi.fn(),
    remove: vi.fn(),
  },
}));

describe('useBroadcastsListConfig - row actions column (D-1)', () => {
  it('renders a trailing, non-reorderable, non-sortable "actions" column', () => {
    const { result } = renderHook(() => useBroadcastsListConfig('wsp-1'));
    const columns = result.current.columns;
    const last = columns[columns.length - 1];
    expect(last.id).toBe('actions');
    expect(last.meta).toEqual({ reorderable: false });
    expect(last.enableSorting).toBe(false);
    expect(last.enableHiding).toBe(false);
    expect(last.enableResizing).toBe(false);
  });

  it('the actions column is the only new addition - every other column is unchanged', () => {
    const { result } = renderHook(() => useBroadcastsListConfig('wsp-1'));
    const ids = result.current.columns.map((c) => c.id);
    expect(ids).toEqual([
      'select', 'name', 'labels', 'channel', 'audience', 'recipients',
      'status', 'scheduledAt', 'counts', 'createdBy', 'createdAt', 'actions',
    ]);
  });

  it('config.actions is wired straight from useBroadcastActions (row surfaces reach this column)', () => {
    const { result } = renderHook(() => useBroadcastsListConfig('wsp-1'));
    const editAction = result.current.actions.find((a) => a.id === 'edit');
    expect(editAction?.surfaces.row).toBe(true);
    const deleteAction = result.current.actions.find((a) => a.id === 'delete');
    expect(deleteAction?.surfaces.row).toBe(true);
    expect(deleteAction?.deferred).toEqual({ actionKey: 'broadcasts.delete', entityType: 'broadcast' });
  });
});
