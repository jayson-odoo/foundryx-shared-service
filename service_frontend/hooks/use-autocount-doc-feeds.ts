'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import type { DocFeedsView } from '@/types/autocount';

/**
 * Document feeds (sprint-5/14, D17) - the ONE hook the "Document feeds" tab
 * and its dialogs read/act through (UI -> hook -> service -> api-client, the
 * house layering rule). Re-fetches the whole `DocFeedsView` (all three
 * feeds) rather than one feed at a time - the tab always shows all three
 * together, so there is never a reason to fetch less.
 *
 * Polls every `pollMs` (default 5s) ONLY while something is genuinely in
 * flight - a run with no outcome yet, or a backfill that is `running`/
 * `stopping` - so an idle tab never polls at all (D14's "no lost tick, no
 * skip-row noise" applies to the CLIENT'S own network chatter too).
 */

function hasInFlight(view: DocFeedsView | null): boolean {
  if (!view) return false;
  return view.feeds.some(
    (feed) =>
      (feed.lastRun && feed.lastRun.outcome === null) ||
      (feed.backfill && (feed.backfill.status === 'running' || feed.backfill.status === 'stopping')),
  );
}

export interface UseAutocountDocFeedsResult {
  view: DocFeedsView | null;
  loading: boolean;
  error: string | null;
  /** Re-fetch now (e.g. right after Configure/Run now/Backfill actions) -
   * the poll loop above is a SAFETY NET, not the primary refresh path. */
  reload: () => Promise<void>;
}

export function useAutocountDocFeeds(
  companyId: string,
  pollMs: number = 5000,
): UseAutocountDocFeedsResult {
  const [view, setView] = useState<DocFeedsView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef(0);

  const load = useCallback(async () => {
    const token = ++tokenRef.current;
    try {
      const next = await autocountService.getDocFeeds(companyId);
      if (token !== tokenRef.current) return;
      setView(next);
      setError(null);
    } catch (e) {
      if (token !== tokenRef.current) return;
      setError(e instanceof Error ? e.message : 'The document feeds could not be loaded.');
    } finally {
      if (token === tokenRef.current) setLoading(false);
    }
  }, [companyId]);

  // First load (and any load driven by a companyId change) - always exactly
  // once, independent of the poll loop below.
  useEffect(() => {
    setLoading(true);
    void load();
    // Invalidate any poll still in flight for the PREVIOUS companyId/load.
    return () => {
      tokenRef.current += 1;
    };
  }, [load]);

  // The poll loop - re-armed only while the just-loaded view has something
  // in flight; settles (no more timers) the moment it doesn't.
  useEffect(() => {
    if (!hasInFlight(view)) return;
    const id = setTimeout(() => {
      void load();
    }, pollMs);
    return () => clearTimeout(id);
  }, [view, pollMs, load]);

  return { view, loading, error, reload: load };
}
