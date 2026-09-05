/**
 * `useConversations` - Team Inbox additions (plan 28, roadmap A8, AC-TEM-44
 * slice content): `teamId` scopes the fetched page client-side (via the S0
 * overlay) and the selection round-trips through the URL so a reload
 * restores it.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useConversations } from './use-conversations';
import type { ConversationThread } from '@/types/omnichannel';

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

const listThreads = vi.fn();
vi.mock('@/services/conversation-service', () => ({
  conversationService: {
    listThreads: (...args: unknown[]) => listThreads(...args),
    subscribe: () => () => {},
  },
}));

const overlays: Record<string, { assignedTeamId: string | null; assignedTeamName: string | null }> = {};
vi.mock('@/services/team-assignment-service', () => ({
  teamAssignmentService: {
    assignTeam: vi.fn(),
    overlayFor: (contactId: string) => overlays[contactId] ?? { assignedTeamId: null, assignedTeamName: null },
  },
}));

describe('useConversations - Team Inbox (plan 28)', () => {
  beforeEach(() => {
    listThreads.mockReset();
    window.history.replaceState(null, '', '/omnichannel/inbox');
    Object.keys(overlays).forEach((k) => delete overlays[k]);
  });
  afterEach(() => {
    window.history.replaceState(null, '', '/omnichannel/inbox');
  });

  it('scopes the list to a selected team (client-side, via the overlay)', async () => {
    overlays['cnt-1'] = { assignedTeamId: 'team-1', assignedTeamName: 'Support' };
    listThreads.mockResolvedValue([thread({ id: 'cnt-1' }), thread({ id: 'cnt-2' })]);

    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.threads.map((t) => t.id)).toEqual(['cnt-1', 'cnt-2']);

    act(() => result.current.setFilters({ teamId: 'team-1' }));
    await waitFor(() =>
      expect(result.current.threads.map((t) => t.id)).toEqual(['cnt-1']),
    );
  });

  it('round-trips the selected team + unassigned-only through the URL', async () => {
    listThreads.mockResolvedValue([]);
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
    listThreads.mockResolvedValue([]);

    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.filters.teamId).toBe('team-2');
    expect(result.current.filters.assignee).toBe('unassigned');
  });
});
