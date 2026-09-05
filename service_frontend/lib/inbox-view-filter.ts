/**
 * Pure client-side filter/sort layer for the inbox view rail + filter bar
 * (plan 27, AC-IVE-15/16). The real thread-list route (`GET
 * /omnichannel/contacts`) does not understand the new dimensions yet
 * (lands S1/S2) - `use-conversations.ts` still calls the REAL `listThreads`
 * for the base set (today's assignee/status/priority/search), then applies
 * this layer over the result so the rail + Show/Sort/Unreplied are tunable
 * against real demo data with no backend change.
 *
 * // S0 MOCK approximation - `unreplied` proxies via `unreadCount > 0` (the
 * real semantics need `contacts.last_agent_message_at`, AC-IVE-11, which
 * lands S1). `longest_waiting` orders the unreplied-proxy set by
 * `lastIncomingMessageAt` ascending, exactly like the real AC-IVE-16 rule
 * once the real column exists - only the "is it unreplied" test is a stand-in.
 */
import type { ConversationThread, ThreadSort } from '@/types/omnichannel';

export interface InboxViewFilterInput {
  lifecycleStageIds: string[];
  tagIds: string[];
  channelIds: string[];
  unreplied: boolean;
  sort: ThreadSort;
}

/** S0 proxy for "has the contact replied since the last inbound message". */
export function isUnrepliedProxy(t: ConversationThread): boolean {
  return t.unreadCount > 0;
}

function byNewest(a: ConversationThread, b: ConversationThread): number {
  return (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? '');
}

export function applyInboxViewFilters(
  threads: ConversationThread[],
  filters: InboxViewFilterInput,
): ConversationThread[] {
  let result = threads;

  if (filters.lifecycleStageIds.length > 0) {
    const ids = new Set(filters.lifecycleStageIds);
    result = result.filter((t) => !!t.lifecycle && ids.has(t.lifecycle.statusId));
  }
  if (filters.tagIds.length > 0) {
    const ids = new Set(filters.tagIds);
    result = result.filter((t) => t.tags.some((tag) => ids.has(tag.id)));
  }
  if (filters.channelIds.length > 0) {
    const ids = new Set(filters.channelIds);
    result = result.filter((t) => !!t.channelId && ids.has(t.channelId));
  }
  if (filters.unreplied) {
    result = result.filter(isUnrepliedProxy);
  }

  const sorted = [...result];
  switch (filters.sort) {
    case 'oldest':
      sorted.sort((a, b) => (a.lastMessageAt ?? '').localeCompare(b.lastMessageAt ?? ''));
      break;
    case 'unreplied_first':
      sorted.sort((a, b) => {
        const ua = isUnrepliedProxy(a) ? 0 : 1;
        const ub = isUnrepliedProxy(b) ? 0 : 1;
        return ua !== ub ? ua - ub : byNewest(a, b);
      });
      break;
    case 'longest_waiting':
      sorted.sort((a, b) => {
        const ua = isUnrepliedProxy(a) ? 0 : 1;
        const ub = isUnrepliedProxy(b) ? 0 : 1;
        if (ua !== ub) return ua - ub;
        if (ua === 0) {
          return (a.lastIncomingMessageAt ?? '').localeCompare(b.lastIncomingMessageAt ?? '');
        }
        return byNewest(a, b);
      });
      break;
    case 'newest':
    default:
      sorted.sort(byNewest);
      break;
  }
  return sorted;
}
