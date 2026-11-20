'use client';

/**
 * The inbox page's state (plan 05 §6, plan 27 D-A3-15), shared by both looks
 * of `inbox/page.tsx` so they cannot drift: the resolved workspace, the thread
 * list (`useConversations`), the open conversation and its `?thread=` deep
 * link, and the Back behaviour of the phone layout.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  useConversations,
  type UseConversationsResult,
} from '@/hooks/use-conversations';
import { useMediaQuery } from '@/hooks/use-media-query';
import { workspaceService } from '@/services/workspace-service';

/** Rail sits beside the list at >=1024px (`lg`); below it the shell is ONE
 *  pane (AC-IVE-24) and the rail collapses into a View `SearchSelect`. */
export const DESKTOP_RAIL_QUERY = '(min-width: 1024px)';

export interface UseInboxPageResult {
  workspaceId: string | null;
  conversations: UseConversationsResult;
  selectedId: string | null;
  isDesktop: boolean;
  openThread: (id: string | null) => void;
  backToList: () => void;
}

export function useInboxPage(): UseInboxPageResult {
  // Resolve the workspace (default first). A workspace switcher rides in when
  // multi-workspace inbox UX lands (plan 05 keeps the host thin).
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  useEffect(() => {
    workspaceService
      .list({ page: 0, pageSize: 50 })
      .then((res) => {
        const ws = res.data.find((w) => w.isDefault) ?? res.data[0];
        setWorkspaceId(ws?.id ?? null);
      })
      .catch(() => setWorkspaceId(null));
  }, []);

  const conversations = useConversations(workspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const isDesktop = useMediaQuery(DESKTOP_RAIL_QUERY);

  // Deep link: ?thread=<contactId> is the source of truth for the open
  // conversation - opening a thread pushes it into the URL (shareable +
  // debuggable), and browser back/forward re-selects. Read from window/history
  // instead of useSearchParams to keep the route statically prerenderable.
  useEffect(() => {
    const sync = () =>
      setSelectedId(new URLSearchParams(window.location.search).get('thread'));
    sync(); // initial deep link
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);

  // F5 (round-3 codex triage) - whether the CURRENTLY open thread was opened
  // by an in-app click (a real history entry exists for the pre-open "list"
  // state, so the device's native Back can simply pop it) vs a deep link
  // (page loaded directly at `?thread=`, no such entry to pop back TO).
  const openedViaClickRef = useRef(false);

  const openThread = useCallback((id: string | null) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('thread', id);
    else url.searchParams.delete('thread');
    // Same thread re-click = no history spam; a new thread = a back-navigable entry.
    if (id !== new URLSearchParams(window.location.search).get('thread')) {
      window.history.pushState(null, '', url);
      if (id) openedViaClickRef.current = true;
    }
  }, []);

  // F5 - the mobile "Back to conversations" control. Closing a thread by
  // PUSHING a fresh no-thread entry (the old behavior, same code path as
  // opening a thread) left the browser's OWN back button one tap short of
  // leaving the inbox: [list] -> [thread] -> [list, via this button] means a
  // native Back press lands back on [thread] - REOPENING the very
  // conversation the user just backed out of. For an app-opened thread,
  // `history.back()` pops the entry `openThread` pushed, landing correctly
  // on the ORIGINAL [list] state with no extra entry (the `popstate`
  // listener syncs `selectedId` from the URL, so no manual state set here).
  // A deep-linked thread (no prior in-app "list" entry exists to pop back
  // to) falls back to `replaceState`, swapping the URL in place instead of
  // navigating the tab away from the inbox entirely.
  const backToList = useCallback(() => {
    if (openedViaClickRef.current) {
      openedViaClickRef.current = false;
      window.history.back();
      return;
    }
    setSelectedId(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('thread');
    window.history.replaceState(null, '', url);
  }, []);

  return {
    workspaceId,
    conversations,
    selectedId,
    isDesktop,
    openThread,
    backToList,
  };
}
