'use client';

import { useEffect, useState } from 'react';

/**
 * Generic CSS media-query hook (mirrors `useIsMobile`'s pattern, parametrized).
 * `undefined` on the very first render (SSR-safe); resolves on mount + tracks
 * changes live (used to pick the Contact panel's right-pane vs Sheet layout at
 * the ~1280px breakpoint, plan 25 D14).
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}
