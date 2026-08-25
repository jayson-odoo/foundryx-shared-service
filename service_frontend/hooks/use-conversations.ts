'use client';

/**
 * Inbox thread-list state (plan 05): filters + fetch + live updates.
 * Socket events patch rows in place (no refetch): `message.created` /
 * `contact.updated` upsert the thread and re-sort by lastMessageAt desc.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import type {
  ConversationSocketEvent,
  ConversationThread,
  ThreadListQuery,
  ThreadPriority,
  ThreadStatus,
} from '@/types/omnichannel';

import { useConversationSocket } from './use-conversation-socket';

export interface ConversationFilters {
  assignee: 'all' | 'me' | 'unassigned';
  status: ThreadStatus | 'ALL';
  priority: ThreadPriority | 'ALL';
  search: string;
}

export interface UseConversationsResult {
  threads: ConversationThread[];
  isLoading: boolean;
  error: string | null;
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  reload: () => void;
}

const DEFAULT_FILTERS: ConversationFilters = {
  assignee: 'all',
  status: 'ALL',
  priority: 'ALL',
  search: '',
};

function sortThreads(list: ConversationThread[]): ConversationThread[] {
  return [...list].sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''));
}

export function useConversations(workspaceId: string | null | undefined): UseConversationsResult {
  const [threads, setThreads] = useState<ConversationThread[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<ConversationFilters>(DEFAULT_FILTERS);
  const fetchSeq = useRef(0);

  const query = useMemo<ThreadListQuery>(
    () => ({
      workspaceId: workspaceId ?? undefined,
      assignee: filters.assignee,
      status: filters.status,
      priority: filters.priority,
      search: filters.search || undefined,
    }),
    [workspaceId, filters],
  );

  const load = useCallback(() => {
    if (!workspaceId) return;
    const seq = ++fetchSeq.current;
    setIsLoading(true);
    conversationService
      .listThreads(query)
      .then((list) => {
        if (seq !== fetchSeq.current) return; // stale response - a newer fetch won
        setThreads(list);
        setError(null);
      })
      .catch((e: unknown) => {
        if (seq !== fetchSeq.current) return;
        setError(e instanceof Error ? e.message : 'Could not load conversations');
      })
      .finally(() => {
        if (seq === fetchSeq.current) setIsLoading(false);
      });
  }, [workspaceId, query]);

  useEffect(load, [load]);

  // Live updates. Unfiltered view: upsert the event's thread in place and
  // re-sort (cheap). Filtered view: the event may move a thread IN or OUT of
  // the current bucket (e.g. self-claim leaves Unassigned) and 'me' can only
  // be resolved server-side - reconcile with a refetch instead of guessing.
  const isFiltered =
    filters.assignee !== 'all' ||
    filters.status !== 'ALL' ||
    filters.priority !== 'ALL' ||
    !!filters.search;
  const onEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (event.type === 'message.status') return; // tick updates live in the drawer
      if (event.type === 'message.reaction') return; // chips update in the drawer, not the list
      if (isFiltered) {
        load();
        return;
      }
      const thread = event.thread;
      setThreads((prev) => {
        const rest = prev.filter((t) => t.id !== thread.id);
        return sortThreads([...rest, thread]);
      });
    },
    [isFiltered, load],
  );
  useConversationSocket(workspaceId, onEvent);

  const setFilters = useCallback((patch: Partial<ConversationFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...patch }));
  }, []);

  return { threads, isLoading, error, filters, setFilters, reload: load };
}
