import { describe, expect, it } from 'vitest';

import { applyInboxViewFilters, isUnrepliedProxy } from './inbox-view-filter';
import type { ConversationThread } from '@/types/omnichannel';

function thread(over: Partial<ConversationThread> = {}): ConversationThread {
  return {
    id: over.id ?? 'cnt-1',
    tenantId: 'default',
    workspaceId: 'wsp-001',
    name: 'Contact',
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
    channelId: 'chn-1',
    channelType: 'WHATSAPP',
    cswExpiresAt: null,
    lastIncomingMessageAt: null,
    lastMessageAt: null,
    lastMessagePreview: null,
    unreadCount: 0,
    customFields: {},
    tags: [],
    lifecycle: null,
    createdAt: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('isUnrepliedProxy', () => {
  it('treats any unread inbound as unreplied (S0 approximation)', () => {
    expect(isUnrepliedProxy(thread({ unreadCount: 1 }))).toBe(true);
    expect(isUnrepliedProxy(thread({ unreadCount: 0 }))).toBe(false);
  });
});

describe('applyInboxViewFilters', () => {
  it('filters by lifecycleStageIds against thread.lifecycle.statusId', () => {
    const a = thread({ id: 'a', lifecycle: { statusId: 'stg-1', key: 'k', label: 'K', color: null, isWon: false, isLost: false } });
    const b = thread({ id: 'b', lifecycle: { statusId: 'stg-2', key: 'k2', label: 'K2', color: null, isWon: false, isLost: false } });
    const result = applyInboxViewFilters([a, b], {
      lifecycleStageIds: ['stg-1'],
      tagIds: [],
      channelIds: [],
      unreplied: false,
      sort: 'newest',
    });
    expect(result.map((t) => t.id)).toEqual(['a']);
  });

  it('filters by tagIds', () => {
    const a = thread({ id: 'a', tags: [{ id: 'tag-1', name: 'VIP', emoji: null, color: null }] });
    const b = thread({ id: 'b', tags: [] });
    const result = applyInboxViewFilters([a, b], {
      lifecycleStageIds: [],
      tagIds: ['tag-1'],
      channelIds: [],
      unreplied: false,
      sort: 'newest',
    });
    expect(result.map((t) => t.id)).toEqual(['a']);
  });

  it('unreplied keeps only the unread-proxy threads', () => {
    const a = thread({ id: 'a', unreadCount: 2 });
    const b = thread({ id: 'b', unreadCount: 0 });
    const result = applyInboxViewFilters([a, b], {
      lifecycleStageIds: [],
      tagIds: [],
      channelIds: [],
      unreplied: true,
      sort: 'newest',
    });
    expect(result.map((t) => t.id)).toEqual(['a']);
  });

  it('sorts newest/oldest by lastMessageAt', () => {
    const older = thread({ id: 'older', lastMessageAt: '2026-01-01T00:00:00Z' });
    const newer = thread({ id: 'newer', lastMessageAt: '2026-02-01T00:00:00Z' });
    const newest = applyInboxViewFilters([older, newer], {
      lifecycleStageIds: [], tagIds: [], channelIds: [], unreplied: false, sort: 'newest',
    });
    expect(newest.map((t) => t.id)).toEqual(['newer', 'older']);
    const oldest = applyInboxViewFilters([older, newer], {
      lifecycleStageIds: [], tagIds: [], channelIds: [], unreplied: false, sort: 'oldest',
    });
    expect(oldest.map((t) => t.id)).toEqual(['older', 'newer']);
  });

  it('unreplied_first puts unreplied-proxy threads ahead regardless of recency', () => {
    const repliedRecent = thread({ id: 'replied', unreadCount: 0, lastMessageAt: '2026-02-01T00:00:00Z' });
    const unrepliedOld = thread({ id: 'unreplied', unreadCount: 3, lastMessageAt: '2026-01-01T00:00:00Z' });
    const result = applyInboxViewFilters([repliedRecent, unrepliedOld], {
      lifecycleStageIds: [], tagIds: [], channelIds: [], unreplied: false, sort: 'unreplied_first',
    });
    expect(result.map((t) => t.id)).toEqual(['unreplied', 'replied']);
  });

  it('longest_waiting orders the unreplied set by lastIncomingMessageAt ascending', () => {
    const waitingLonger = thread({ id: 'longer', unreadCount: 1, lastIncomingMessageAt: '2026-01-01T00:00:00Z' });
    const waitingShorter = thread({ id: 'shorter', unreadCount: 1, lastIncomingMessageAt: '2026-01-05T00:00:00Z' });
    const replied = thread({ id: 'replied', unreadCount: 0, lastMessageAt: '2026-01-10T00:00:00Z' });
    const result = applyInboxViewFilters([replied, waitingShorter, waitingLonger], {
      lifecycleStageIds: [], tagIds: [], channelIds: [], unreplied: false, sort: 'longest_waiting',
    });
    expect(result.map((t) => t.id)).toEqual(['longer', 'shorter', 'replied']);
  });
});
