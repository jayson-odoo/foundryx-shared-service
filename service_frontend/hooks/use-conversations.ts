'use client';

/**
 * Inbox thread-list state (plan 05): filters + fetch + live updates.
 * Socket events patch rows in place (no refetch): `message.created` /
 * `contact.updated` upsert the thread and re-sort by lastMessageAt desc.
 *
 * Plan 27 (AC-IVE-15/16) adds the view-rail dimensions - `lifecycleStageIds`/
 * `tagIds`/`channelIds`/`unreplied`/`sort`/`viewId`. ALL filtering and sorting
 * happens server-side (`GET /omnichannel/contacts`, S2) - the hook only
 * carries the filter state + issues the fetch; no client-side re-filter/
 * re-sort layer (the S0 `applyInboxViewFilters` proxy is retired).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import type {
  ConversationSocketEvent,
  ConversationThread,
  ThreadListQuery,
  ThreadPriority,
  ThreadSort,
  ThreadStatus,
} from '@/types/omnichannel';

import { useConversationSocket } from './use-conversation-socket';

export interface ConversationFilters {
  assignee: 'all' | 'me' | 'unassigned';
  status: ThreadStatus | 'ALL';
  /** F2 (round-3 codex triage) - true ONLY when the user picked `status` via
   *  the filter bar's own control; false when it reads 'ALL' because a
   *  multi-status saved view collapsed into that single-value display
   *  (`expandViewFilter`). The service only sends `status` as an explicit
   *  override (clearing the view's stored value server-side) when this is
   *  true - otherwise it is omitted so the view's real multi-status set
   *  applies server-side. */
  statusExplicit: boolean;
  priority: ThreadPriority | 'ALL';
  search: string;
  /** View-rail dimensions (plan 27). */
  lifecycleStageIds: string[];
  tagIds: string[];
  channelIds: string[];
  unreplied: boolean;
  sort: ThreadSort;
  /** The selected saved view, if any - carried for the URL (`?view=`) and to
   *  highlight the rail; the FILTER fields above are the source of truth for
   *  what actually gets requested (a view is expanded into them on select). */
  viewId: string | null;
}

export interface UseConversationsResult {
  threads: ConversationThread[];
  isLoading: boolean;
  error: string | null;
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  reload: () => void;
}

export const DEFAULT_FILTERS: ConversationFilters = {
  assignee: 'all',
  status: 'ALL',
  statusExplicit: false,
  priority: 'ALL',
  search: '',
  lifecycleStageIds: [],
  tagIds: [],
  channelIds: [],
  unreplied: false,
  sort: 'newest',
  viewId: null,
};

function sortThreads(list: ConversationThread[]): ConversationThread[] {
  return [...list].sort((a, b) => (b.lastMessageAt ?? '').localeCompare(a.lastMessageAt ?? ''));
}

export function useConversations(workspaceId: string | null | undefined): UseConversationsResult {
  const [rawThreads, setRawThreads] = useState<ConversationThread[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<ConversationFilters>(DEFAULT_FILTERS);
  const fetchSeq = useRef(0);

  // F10 (round-3 codex triage) - EVERY view-rail dimension carried in
  // `filters` (lifecycleStageIds/tagIds/channelIds/viewId) is scoped to the
  // PREVIOUS workspace. Without a reset, switching workspaces re-fetches
  // with the OLD workspace's ids against the NEW one: a `viewId` from
  // another workspace 404s the whole list outright (the router's own
  // cross-workspace guard), and a stale tag/channel id now 422s under B11's
  // validation - either way the list breaks instead of showing the new
  // workspace's "All" state. `rawThreads` is reset too so a broken/slow new
  // fetch never leaves the OLD workspace's rows on screen looking current.
  // Reset happens DURING RENDER (the sanctioned "derived state from a
  // changed prop" pattern - React re-renders before committing/running
  // effects) so `load()`'s effect below never fires with the stale
  // workspaceId+filters combination even transiently.
  const prevWorkspaceIdRef = useRef(workspaceId);
  if (prevWorkspaceIdRef.current !== workspaceId) {
    prevWorkspaceIdRef.current = workspaceId;
    if (filters !== DEFAULT_FILTERS) setFiltersState(DEFAULT_FILTERS);
    setRawThreads([]);
  }

  const query = useMemo<ThreadListQuery>(
    () => ({
      workspaceId: workspaceId ?? undefined,
      assignee: filters.assignee,
      status: filters.status,
      statusExplicit: filters.statusExplicit,
      priority: filters.priority,
      search: filters.search || undefined,
      lifecycleStageIds: filters.lifecycleStageIds,
      tagIds: filters.tagIds,
      channelIds: filters.channelIds,
      unreplied: filters.unreplied,
      sort: filters.sort,
      viewId: filters.viewId,
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
        setRawThreads(list);
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
  // A non-default sort or an active saved view ALSO needs a refetch (the fast
  // path below only ever re-sorts by lastMessageAt desc, and a view's stored
  // filter can carry dimensions beyond what's mirrored into these fields).
  const isFiltered =
    filters.assignee !== 'all' ||
    filters.status !== 'ALL' ||
    filters.priority !== 'ALL' ||
    !!filters.search ||
    filters.lifecycleStageIds.length > 0 ||
    filters.tagIds.length > 0 ||
    filters.channelIds.length > 0 ||
    filters.unreplied ||
    filters.sort !== 'newest' ||
    !!filters.viewId;
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
      const thread = event.thread;
      setRawThreads((prev) => {
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

  // Server-filtered + server-sorted (AC-IVE-15/16) - `rawThreads` is already
  // the exact page the backend computed for the current `query`.
  return { threads: rawThreads, isLoading, error, filters, setFilters, reload: load };
}
