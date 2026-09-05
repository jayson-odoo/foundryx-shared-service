'use client';

/**
 * Inbox thread-list state (plan 05): filters + fetch + live updates.
 * Socket events patch rows in place (no refetch): `message.created` /
 * `contact.updated` upsert the thread and re-sort by lastMessageAt desc.
 *
 * Plan 28 (roadmap A8, S0 mock): `teamId` scopes the list to a Team Inbox
 * (the rail's Teams section). The real backend gains a `teamId` list filter
 * in S2 - until then this hook applies it CLIENT-SIDE over the fetched page,
 * merged with the S0 team-assignment overlay (`services/team-assignment-
 * service.ts`) so the rail is fully tunable with no backend support.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import { teamAssignmentService } from '@/services/team-assignment-service';
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
  /** Team Inbox scope (plan 28) - null = every team + no team. */
  teamId: string | null;
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
  teamId: null,
};

/** Initial `teamId`/`assignee` from the URL (AC-TEM-44 - "a reload restores
 * it"). Read once on mount; SSR-safe (the route is client-rendered anyway). */
function readInitialFilters(): Pick<ConversationFilters, 'teamId' | 'assignee'> {
  if (typeof window === 'undefined') return { teamId: null, assignee: 'all' };
  const params = new URLSearchParams(window.location.search);
  const assignee = params.get('assignee');
  return {
    teamId: params.get('team'),
    assignee: assignee === 'me' || assignee === 'unassigned' ? assignee : 'all',
  };
}

function sortThreads(list: ConversationThread[]): ConversationThread[] {
  return [...list].sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''));
}

function withTeamOverlay(thread: ConversationThread): ConversationThread {
  return { ...thread, ...teamAssignmentService.overlayFor(thread.id) };
}

export function useConversations(workspaceId: string | null | undefined): UseConversationsResult {
  const [threads, setThreads] = useState<ConversationThread[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<ConversationFilters>(() => ({
    ...DEFAULT_FILTERS,
    ...readInitialFilters(),
  }));
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
        const merged = list.map(withTeamOverlay);
        const scoped = filters.teamId
          ? merged.filter((t) => t.assignedTeamId === filters.teamId)
          : merged;
        setThreads(scoped);
        setError(null);
      })
      .catch((e: unknown) => {
        if (seq !== fetchSeq.current) return;
        setError(e instanceof Error ? e.message : 'Could not load conversations');
      })
      .finally(() => {
        if (seq === fetchSeq.current) setIsLoading(false);
      });
  }, [workspaceId, query, filters.teamId]);

  useEffect(load, [load]);

  // Rail selection -> URL (AC-TEM-44 "a reload restores it"). `replaceState`
  // (no history spam) - only the two rail-driven params are represented.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (filters.teamId) url.searchParams.set('team', filters.teamId);
    else url.searchParams.delete('team');
    if (filters.teamId && filters.assignee === 'unassigned') {
      url.searchParams.set('assignee', 'unassigned');
    } else {
      url.searchParams.delete('assignee');
    }
    window.history.replaceState(null, '', url);
  }, [filters.teamId, filters.assignee]);

  // Live updates. Unfiltered view: upsert the event's thread in place and
  // re-sort (cheap). Filtered view: the event may move a thread IN or OUT of
  // the current bucket (e.g. self-claim leaves Unassigned) and 'me'/teamId can
  // only be resolved server-side (or, for teamId, via the mock overlay) -
  // reconcile with a refetch instead of guessing.
  const isFiltered =
    filters.assignee !== 'all' ||
    filters.status !== 'ALL' ||
    filters.priority !== 'ALL' ||
    !!filters.search ||
    !!filters.teamId;
  const onEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (event.type === 'message.status') return; // tick updates live in the drawer
      if (event.type === 'message.reaction') return; // chips update in the drawer, not the list
      // F2: the WS subscription is scoped per-workspace server-side, but a
      // stale/reused connection (or a mock/test double with no server-side
      // room filtering) could still deliver a foreign workspace's event -
      // never let one upsert a row into a DIFFERENT workspace's list.
      if (event.thread.workspaceId !== workspaceId) return;
      if (isFiltered) {
        load();
        return;
      }
      const thread = withTeamOverlay(event.thread);
      setThreads((prev) => {
        const rest = prev.filter((t) => t.id !== thread.id);
        return sortThreads([...rest, thread]);
      });
    },
    [isFiltered, load, workspaceId],
  );
  useConversationSocket(workspaceId, onEvent);

  const setFilters = useCallback((patch: Partial<ConversationFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...patch }));
  }, []);

  return { threads, isLoading, error, filters, setFilters, reload: load };
}
