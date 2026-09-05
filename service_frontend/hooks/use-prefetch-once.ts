'use client';

import { useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';

/**
 * `router.prefetch(href)`, at most once per href for the life of the
 * component (AC-DLA-14, AC-DLA-34).
 *
 * Shared by every hover-prefetch call site so the "once per href" rule lives
 * in one place: a clickable `DataGrid` row (`components/ui/data-grid-table.tsx`
 * `DataGridTableBodyRow`) is the first T2 adopter; the sidebar menu and the
 * record pager's prev/next neighbours are T4 territory.
 *
 * Ported (API-compatible) from `sorento_crm` `hooks/usePrefetchOnce.ts`
 * (integration/ui-motion-round2, M4).
 */
export function usePrefetchOnce() {
  const router = useRouter();
  const seen = useRef<Set<string>>(new Set());

  return useCallback(
    (href: string) => {
      // A touch device fires `pointerenter` on the tap that is already
      // opening the record, so the prefetch is pure cost there. Asked as
      // `hover: none` rather than `!(hover: hover)` on purpose: a stub
      // `matchMedia` that answers "no match" to everything (jsdom's, the one
      // every test in this repo runs against) would read the negative form as
      // "no hover" and switch prefetching off everywhere.
      if (typeof window !== 'undefined' && window.matchMedia?.('(hover: none)').matches) return;
      if (seen.current.has(href)) return;
      seen.current.add(href);
      // Optional: the real `useRouter()` always returns one, but a test that
      // mocks `next/navigation` with only `push` must not turn every linkable
      // row into a `router.prefetch is not a function` throw.
      router.prefetch?.(href);
    },
    [router],
  );
}
