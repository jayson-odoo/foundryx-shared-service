/**
 * Round-3 codex triage F10 - workspace switch must reset filters/rows, not
 * carry the PREVIOUS workspace's view-rail dimensions (lifecycleStageIds/
 * tagIds/channelIds/viewId) into a query scoped to the NEW workspace (a
 * `viewId` from another workspace 404s outright server-side; a stale tag/
 * channel id now 422s under B11's validation).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConversationThread, ThreadListQuery } from '@/types/omnichannel';

import { DEFAULT_FILTERS, useConversations } from './use-conversations';

const { listThreadsMock, subscribeMock } = vi.hoisted(() => ({
  listThreadsMock: vi.fn(),
  subscribeMock: vi.fn(() => () => {}),
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listThreads: listThreadsMock, subscribe: subscribeMock },
}));

function thread(id: string, workspaceId: string): ConversationThread {
  return {
    id, workspaceId, firstName: null, lastName: null, phone: '+60000000000',
    status: 'OPEN', priority: 'MEDIUM', assignedUserId: null, assignedUserName: null,
    lastMessageAt: '2026-01-01T00:00:00Z', lastMessagePreview: null, unreadCount: 0,
    channelId: null, cswExpiresAt: null,
  } as unknown as ConversationThread;
}

beforeEach(() => {
  listThreadsMock.mockReset();
  subscribeMock.mockClear();
  listThreadsMock.mockResolvedValue([]);
});

describe('useConversations - workspace switch reset (F10)', () => {
  it('resets filters, rows, and the query on a workspace change', async () => {
    listThreadsMock.mockResolvedValueOnce([thread('cnt-1', 'wsp-a')]);
    const { result, rerender } = renderHook(
      ({ workspaceId }: { workspaceId: string }) => useConversations(workspaceId),
      { initialProps: { workspaceId: 'wsp-a' } },
    );

    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    // Apply a workspace-A-scoped filter (a saved view + a tag - exactly the
    // dimensions that must not survive the switch).
    act(() => {
      result.current.setFilters({
        viewId: 'view-a-1', tagIds: ['tag-a-1'], lifecycleStageIds: ['stg-a-1'],
      });
    });
    await waitFor(() =>
      expect(listThreadsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ viewId: 'view-a-1', tagIds: ['tag-a-1'] }),
      ),
    );

    listThreadsMock.mockResolvedValueOnce([thread('cnt-2', 'wsp-b')]);
    rerender({ workspaceId: 'wsp-b' });

    // The filters reset to default BEFORE the new fetch fires - never a
    // request carrying workspace A's viewId/tagIds/lifecycleStageIds against
    // workspace B.
    expect(result.current.filters).toEqual(DEFAULT_FILTERS);
    await waitFor(() => expect(result.current.threads).toEqual([thread('cnt-2', 'wsp-b')]));

    const lastQuery = listThreadsMock.mock.calls.at(-1)![0] as ThreadListQuery;
    expect(lastQuery.workspaceId).toBe('wsp-b');
    expect(lastQuery.viewId).toBeNull();
    expect(lastQuery.tagIds).toEqual([]);
    expect(lastQuery.lifecycleStageIds).toEqual([]);

    // No call was EVER made mixing the new workspace with the old filters.
    for (const call of listThreadsMock.mock.calls) {
      const q = call[0] as ThreadListQuery;
      if (q.workspaceId === 'wsp-b') {
        expect(q.viewId).toBeNull();
        expect(q.tagIds).toEqual([]);
      }
    }
  });

  it('clears stale rows immediately on a workspace switch (never shows the old workspace mid-fetch)', async () => {
    listThreadsMock.mockResolvedValueOnce([thread('cnt-1', 'wsp-a')]);
    const { result, rerender } = renderHook(
      ({ workspaceId }: { workspaceId: string }) => useConversations(workspaceId),
      { initialProps: { workspaceId: 'wsp-a' } },
    );
    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    // A slow-resolving fetch for workspace B - rows must already be cleared
    // synchronously on the switch, not still showing workspace A's thread.
    let resolveB!: (v: ConversationThread[]) => void;
    listThreadsMock.mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve; }));
    rerender({ workspaceId: 'wsp-b' });

    expect(result.current.threads).toEqual([]);

    await act(async () => {
      resolveB([thread('cnt-2', 'wsp-b')]);
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.threads).toEqual([thread('cnt-2', 'wsp-b')]));
  });
});
