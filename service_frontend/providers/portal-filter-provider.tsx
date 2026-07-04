'use client';

import { createContext, useCallback, useContext, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

/**
 * Global event/context filter (Cluster E, slice 0b — AC-06-25). The selected
 * context key lives in the URL (`?ctx=`) so it is durable across navigation and
 * applies app-wide in the portal: every surface reads it from here to narrow to
 * one event. `null` = unfiltered (show items across all contexts).
 */
interface PortalFilterContextValue {
  activeContextKey: string | null;
  setActiveContextKey: (key: string | null) => void;
}

const PortalFilterContext = createContext<PortalFilterContextValue | null>(null);

export function PortalFilterProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeContextKey = searchParams.get('ctx');

  const setActiveContextKey = useCallback(
    (key: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (key) params.set('ctx', key);
      else params.delete('ctx');
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname);
    },
    [router, pathname, searchParams],
  );

  const value = useMemo<PortalFilterContextValue>(
    () => ({ activeContextKey, setActiveContextKey }),
    [activeContextKey, setActiveContextKey],
  );

  return (
    <PortalFilterContext.Provider value={value}>
      {children}
    </PortalFilterContext.Provider>
  );
}

export function usePortalFilter(): PortalFilterContextValue {
  const ctx = useContext(PortalFilterContext);
  if (!ctx) {
    throw new Error('usePortalFilter must be used within a PortalFilterProvider');
  }
  return ctx;
}
