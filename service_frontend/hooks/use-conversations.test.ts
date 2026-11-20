/**
 * `useConversations` covers two independent additions:
 * - Team Inbox (plan 28, roadmap A8, AC-TEM-44): `teamId` is a real,
 *   server-side filter (`GET /omnichannel/contacts?teamId=`) and the
 *   selection round-trips through the URL so a reload restores it.
 * - Round-3 codex triage F10 - workspace switch must reset filters/rows,
 *   not carry the PREVIOUS workspace's view-rail dimensions
 *   (lifecycleStageIds/tagIds/channelIds/viewId) into a query scoped to the
 *   NEW workspace (a `viewId` from another workspace 404s outright
 *   server-side; a stale tag/channel id now 422s under B11's validation).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConversationThread, ThreadListQuery } from '@/types/omnichannel';

const { listThreadsMock, subscribeMock } = vi.hoisted(() => ({
  listThreadsMock: vi.fn(),
  subscribeMock: vi.fn(() => () => {}),
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listThreads: listThreadsMock, subscribe: subscribeMock },
}));

import { DEFAULT_FILTERS, useConversations } from './use-conversations';

function thread(over: Partial<ConversationThread> = {}): ConversationThread {
  return {
    id: 'cnt-1',
    tenantId: 't1',
    workspaceId: 'wsp-1',
    name: 'Someone',
    firstName: null,
    lastName: null,
    phone: null,
    email: null,
    language: null,
    countryCode: null,
    avatarUrl: null,
    assignedUserId: null,
    assignedUserName: null,
    status: 'OPEN',
    priority: 'MEDIUM',
    channelId: null,
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    windowExpiresAt: null,
    humanAgentExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: '2026-06-04T10:00:00Z',
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: {},
    tags: [],
    lifecycle: null,
    createdAt: '2026-06-01T00:00:00Z',
    ...over,
  };
}

describe('useConversations - Team Inbox (plan 28)', () => {
  beforeEach(() => {
    listThreadsMock.mockReset();
    window.history.replaceState(null, '', '/omnichannel/inbox');
  });
  afterEach(() => {
    window.history.replaceState(null, '', '/omnichannel/inbox');
  });

  it('sends the selected team as a server-side filter (AC-TEM-30)', async () => {
    listThreadsMock.mockResolvedValue([
      thread({ id: 'cnt-1', assignedTeamId: 'team-1', assignedTeamName: 'Support' }),
    ]);

    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listThreadsMock).toHaveBeenLastCalledWith(expect.objectContaining({ teamId: null }));

    act(() => result.current.setFilters({ teamId: 'team-1' }));
    await waitFor(() =>
      expect(listThreadsMock).toHaveBeenLastCalledWith(expect.objectContaining({ teamId: 'team-1' })),
    );
    expect(result.current.threads.map((t) => t.id)).toEqual(['cnt-1']);
  });

  it('round-trips the selected team + unassigned-only through the URL', async () => {
    listThreadsMock.mockResolvedValue([]);
    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.setFilters({ teamId: 'team-1', assignee: 'unassigned' }));
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get('team')).toBe('team-1');
      expect(params.get('assignee')).toBe('unassigned');
    });

    // Clearing the team also drops `assignee` from the URL (it only rides
    // alongside a team scope here - the plain Mine/Unassigned tabs are not
    // URL-synced by this hook).
    act(() => result.current.setFilters({ teamId: null, assignee: 'all' }));
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get('team')).toBeNull();
      expect(params.get('assignee')).toBeNull();
    });
  });

  it('reads the initial team + assignee from the URL on mount', async () => {
    window.history.replaceState(null, '', '/omnichannel/inbox?team=team-2&assignee=unassigned');
    listThreadsMock.mockResolvedValue([]);

    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.filters.teamId).toBe('team-2');
    expect(result.current.filters.assignee).toBe('unassigned');
  });
});

function workspaceThread(id: string, workspaceId: string): ConversationThread {
  return {
    id, workspaceId, firstName: null, lastName: null, phone: '+60000000000',
    status: 'OPEN', priority: 'MEDIUM', assignedUserId: null, assignedUserName: null,
    lastMessageAt: '2026-01-01T00:00:00Z', lastMessagePreview: null, unreadCount: 0,
    channelId: null, cswExpiresAt: null,
    // The real backend resolves these on every thread read (plan 28) -
    // no team assigned in this fixture.
    assignedTeamId: null, assignedTeamName: null,
  } as unknown as ConversationThread;
}

describe('useConversations - workspace switch reset (F10)', () => {
  beforeEach(() => {
    listThreadsMock.mockReset();
    subscribeMock.mockClear();
    listThreadsMock.mockResolvedValue([]);
  });

  it('resets filters, rows, and the query on a workspace change', async () => {
    listThreadsMock.mockResolvedValueOnce([workspaceThread('cnt-1', 'wsp-a')]);
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

    listThreadsMock.mockResolvedValueOnce([workspaceThread('cnt-2', 'wsp-b')]);
    rerender({ workspaceId: 'wsp-b' });

    // The filters reset to default BEFORE the new fetch fires - never a
    // request carrying workspace A's viewId/tagIds/lifecycleStageIds against
    // workspace B.
    expect(result.current.filters).toEqual(DEFAULT_FILTERS);
    await waitFor(() => expect(result.current.threads).toEqual([workspaceThread('cnt-2', 'wsp-b')]));

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
    listThreadsMock.mockResolvedValueOnce([workspaceThread('cnt-1', 'wsp-a')]);
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
      resolveB([workspaceThread('cnt-2', 'wsp-b')]);
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.threads).toEqual([workspaceThread('cnt-2', 'wsp-b')]));
  });

  // Plan 28 (roadmap A8) - `InboxPage` always mounts this hook with
  // `workspaceId=null` first (it resolves the default workspace via its own
  // effect), so the null->real transition must NOT be treated as a "switch" -
  // otherwise the `?team=`/`?assignee=` values `readInitialFilters` seeded
  // from the URL on first render get wiped before anyone ever sees them.
  it('does NOT reset filters on the initial null -> real workspaceId resolution', async () => {
    window.history.replaceState(null, '', '/omnichannel/inbox?team=team-9&assignee=unassigned');
    listThreadsMock.mockResolvedValue([]);
    const { result, rerender } = renderHook(
      ({ workspaceId }: { workspaceId: string | null }) => useConversations(workspaceId),
      { initialProps: { workspaceId: null as string | null } },
    );
    expect(result.current.filters.teamId).toBe('team-9');
    expect(result.current.filters.assignee).toBe('unassigned');

    rerender({ workspaceId: 'wsp-a' });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.filters.teamId).toBe('team-9');
    expect(result.current.filters.assignee).toBe('unassigned');
    window.history.replaceState(null, '', '/omnichannel/inbox');
  });
});
