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

  // Resolve total for the carried query, THEN prefetch the prev/next
  // neighbours' form routes (AC-DLA-31) - one more `fetchAt` each, the exact
  // same resolution `goPrev`/`goNext` already do. Sequenced behind the first
  // call (not a second, independent effect) because wrapping needs a real
  // `total` to wrap BY: the first record's "prev" is the LAST record, and
  // fetching that neighbour with a naively unwrapped negative index (-1) hit
  // the endpoint's own validation and 422'd on every single-record-set-of-1
  // form open (caught live - the fetch was harmlessly `.catch()`-swallowed,
  // but wasteful and noisy). Only fires once per `ctx` - a mid-set `i` change
  // from stepping goes through `go()` below, which pushes a brand new URL.
  useEffect(() => {
    if (!query) {
      setTotal(0);
      return;
    }
    let active = true;
    const encodedCtx = encodeListQuery(query);
    const prefetchNeighbour = (total: number, delta: number) => {
      const wrapped = ((index + delta) % total + total) % total;
      if (wrapped === index) return; // total===1: no real neighbour to warm
      fetchAt(query, wrapped)
        .then(({ recordId }) => {
          if (!active || !recordId) return;
          prefetchOnce(buildListNav(buildHref(recordId, encodedCtx, wrapped), { from: recordId }));
        })
        .catch(() => {});
    };
    fetchAt(query, index)
      .then((r) => {
        if (!active) return;
        setTotal(r.total);
        if (r.total > 1) {
          prefetchNeighbour(r.total, -1);
          prefetchNeighbour(r.total, 1);
        }
      })
      .catch(() => {
        if (active) setTotal(0);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx]);

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
