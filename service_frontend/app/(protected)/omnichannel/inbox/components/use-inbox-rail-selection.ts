'use client';

/**
 * Rail/mobile-select selection state (plan 27, AC-IVE-20/24) - shared by the
 * desktop rail and the below-`lg` View `SearchSelect` so both read/write the
 * SAME selection through the SAME URL sync. `?view=` is the source of truth
 * for a reload (raw `window.history`, matching `inbox/page.tsx`'s existing
 * `?thread=` deep-link convention - the route stays statically prerenderable).
 */
import { useCallback, useEffect, useRef } from 'react';

import type { ConversationFilters } from '@/hooks/use-conversations';
import type { InboxView } from '@/types/omnichannel';

import {
  expandViewFilter,
  parseRailKey,
  railSelectionPatch,
  type InboxRailEntry,
  type RailStage,
} from './inbox-rail-entries';

const URL_PARAM = 'view';

function currentUrlKey(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get(URL_PARAM);
}

function writeUrlKey(key: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set(URL_PARAM, key);
  window.history.replaceState(null, '', url);
}

/** Best-effort reconstruction of "what's selected" from the filter state
 *  itself (no separate selection state to fall out of sync). */
export function selectedRailKey(filters: ConversationFilters): string {
  if (filters.viewId) return filters.viewId;
  if (filters.lifecycleStageIds.length === 1) return `lifecycle:${filters.lifecycleStageIds[0]}`;
  return filters.assignee;
}

export interface UseInboxRailSelectionResult {
  selectedKey: string;
  select: (entry: InboxRailEntry) => void;
}

export function useInboxRailSelection(
  filters: ConversationFilters,
  setFilters: (patch: Partial<ConversationFilters>) => void,
  stages: RailStage[],
  views: InboxView[],
  workspaceId: string | null,
): UseInboxRailSelectionResult {
  const restoredRef = useRef(false);
  // F4 (round-3 codex triage) - `restoredRef` used to be "done for the hook's
  // whole lifetime": once the FIRST workspace's `?view=` restored, a later
  // workspace switch (same mounted component, new `stages`/`views` for the
  // new workspace) never re-ran the restoration, and a `?view=` left over
  // from the OLD workspace stayed stuck unresolved against the NEW
  // workspace's data. Track which workspace we last restored FOR and reset
  // the guard when it changes.
  const restoredForWorkspaceRef = useRef<string | null>(null);

  const select = useCallback(
    (entry: InboxRailEntry) => {
      if (entry.kind === 'view') {
        const view = views.find((v) => v.id === entry.viewId);
        setFilters(view ? expandViewFilter(view) : railSelectionPatch(entry));
      } else {
        setFilters(railSelectionPatch(entry));
      }
      writeUrlKey(entry.key);
    },
    [setFilters, views],
  );

  // Restore from `?view=` once the data it might reference (stages/views) has
  // loaded - a reload must land on the same rail entry (AC-IVE-20).
  useEffect(() => {
    if (restoredForWorkspaceRef.current !== workspaceId) {
      restoredRef.current = false;
      restoredForWorkspaceRef.current = workspaceId;
    }
    if (restoredRef.current) return;
    const raw = currentUrlKey();
    if (!raw) {
      restoredRef.current = true;
      return;
    }
    const parsed = parseRailKey(raw);
    if (parsed.kind === 'default') {
      setFilters({ assignee: parsed.value as ConversationFilters['assignee'], lifecycleStageIds: [], tagIds: [], channelIds: [], viewId: null });
      restoredRef.current = true;
      return;
    }
    if (parsed.kind === 'lifecycle') {
      if (stages.length === 0) return; // wait for the graph to load
      if (stages.some((s) => s.id === parsed.value)) {
        setFilters({ assignee: 'all', lifecycleStageIds: [parsed.value], tagIds: [], channelIds: [], viewId: null });
      } else {
        // F4 - an unknown/stale lifecycle key normalizes to All, both the
        // URL and the displayed selection, instead of leaving the address
        // bar pointing at a key nothing in the rail highlights.
        setFilters(railSelectionPatch({ kind: 'default', key: 'all', label: 'All' }));
        writeUrlKey('all');
      }
      restoredRef.current = true;
      return;
    }
    // saved view
    if (views.length === 0) return; // wait for views to load
    const view = views.find((v) => v.id === parsed.value);
    if (view) {
      setFilters(expandViewFilter(view));
    } else {
      // F4 - same normalization for a deleted/foreign saved-view id: fall
      // back to All (URL + filters) rather than a silent no-op that leaves
      // the URL stuck on a view id the rail can never highlight again.
      setFilters(railSelectionPatch({ kind: 'default', key: 'all', label: 'All' }));
      writeUrlKey('all');
    }
    restoredRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stages, views, workspaceId]);

  return { selectedKey: selectedRailKey(filters), select };
}
