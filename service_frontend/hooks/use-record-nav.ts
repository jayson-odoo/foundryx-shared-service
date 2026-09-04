'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ListQuery } from '@/types/resource';
import { buildListNav, decodeListQuery, encodeListQuery } from '@/lib/list-context';
import { usePrefetchOnce } from './use-prefetch-once';

export interface UseRecordNavOptions {
  /** Resolve the record id + total at a position within the carried query. */
  fetchAt: (query: ListQuery, index: number) => Promise<{ recordId: string | null; total: number }>;
  /** Build the form href for a neighbour, preserving ctx + new index. */
  buildHref: (recordId: string, ctx: string, index: number) => string;
}

export interface UseRecordNavResult {
  /** True when a list context is present and there's more than one record. */
  available: boolean;
  index: number; // 0-based position
  total: number;
  isNavigating: boolean;
  goPrev: () => void;
  goNext: () => void;
  /** e.g. "1 / 247" */
  label: string;
}

/**
 * Drives the form's circular "1 / N" record navigation. Reads the carried list
 * query (`ctx`) + position (`i`) from the URL; prev/next re-runs the query at
 * the adjacent offset and navigates to that record. Hidden when no ctx.
 */
export function useRecordNav({ fetchAt, buildHref }: UseRecordNavOptions): UseRecordNavResult {
  const router = useRouter();
  const searchParams = useSearchParams();
  const ctx = searchParams.get('ctx');
  const indexParam = Number(searchParams.get('i'));
  const index = Number.isInteger(indexParam) && indexParam >= 0 ? indexParam : 0;

  const [total, setTotal] = useState(0);
  const [isNavigating, setIsNavigating] = useState(false);
  const prefetchOnce = usePrefetchOnce();

  const query = decodeListQuery(ctx);

  // Resolve total for the carried query (once per ctx).
  useEffect(() => {
    if (!query) {
      setTotal(0);
      return;
    }
    let active = true;
    fetchAt(query, index)
      .then((r) => {
        if (active) setTotal(r.total);
      })
      .catch(() => {
        if (active) setTotal(0);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx]);

  // Prefetch the prev/next neighbours' form routes on mount (AC-DLA-31) - one
  // `fetchAt` each, the exact same resolution `goPrev`/`goNext` already do, so
  // stepping the pager never waits on a round trip it didn't already warm.
  // Each neighbour's own `total` (not the outer `total` state, which may not
  // have resolved yet) decides whether it wraps to a real row.
  useEffect(() => {
    if (!query) return;
    let active = true;
    const encodedCtx = encodeListQuery(query);
    const prefetchNeighbour = (delta: number) => {
      fetchAt(query, index + delta)
        .then(({ recordId, total: neighbourTotal }) => {
          if (!active || !recordId || neighbourTotal <= 1) return;
          const wrapped = ((index + delta) % neighbourTotal + neighbourTotal) % neighbourTotal;
          prefetchOnce(
            buildListNav(buildHref(recordId, encodedCtx, wrapped), { from: recordId }),
          );
        })
        .catch(() => {});
    };
    prefetchNeighbour(-1);
    prefetchNeighbour(1);
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, index]);

  const go = useCallback(
    (nextIndex: number) => {
      if (!query || total <= 0) return;
      const wrapped = ((nextIndex % total) + total) % total; // circular
      setIsNavigating(true);
      fetchAt(query, wrapped)
        .then(({ recordId }) => {
          // `from=<recordId>` (AC-DLA-30/31): the row Back should restore is
          // whichever record the pager is CURRENTLY on, not the one first
          // opened from the list - it updates every step.
          if (recordId) {
            router.push(
              buildListNav(buildHref(recordId, encodeListQuery(query), wrapped), { from: recordId }),
            );
          }
        })
        .finally(() => setIsNavigating(false));
    },
    [query, total, fetchAt, buildHref, router],
  );

  const available = Boolean(query) && total > 1;

  return {
    available,
    index,
    total,
    isNavigating,
    goPrev: () => go(index - 1),
    goNext: () => go(index + 1),
    label: total > 0 ? `${index + 1} / ${total}` : '',
  };
}
