'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useSession } from 'next-auth/react';
import type { InstalledModule, StoreAction, StoreModule } from '@/types/app-store';
import { appStoreService } from '@/services/app-store-service';

/**
 * App Store hooks (plan 08 §8).
 *
 * `useAppStore()` - the storefront/console state machine: catalog + per-module
 * pending actions. Pass a `tenantId` to act on ANOTHER tenant via the operator
 * endpoints (console Modules tab); omit it for the caller's own tenant.
 *
 * `useInstalledModules()` - lightweight install list for menu gating (D7),
 * backed by a module-level store so the sidebar doesn't refetch per render.
 * Store actions on the OWN tenant invalidate it + run NextAuth `update()` so
 * the acting admin's perms/menu refresh immediately; other users converge on
 * next request - the backend 403 (`require_module`) is the real boundary.
 */

/* ─────────────── installed-modules store (menu gating) ─────────────── */

type InstalledState = {
  /** null until the first fetch resolves (avoids flicker-hiding menu items). */
  modules: InstalledModule[] | null;
};

let installedState: InstalledState = { modules: null };
let installedPromise: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

function fetchInstalled(): Promise<void> {
  installedPromise ??= appStoreService
    .installed()
    .then((modules) => {
      installedState = { modules };
    })
    .catch(() => {
      // Menu gating degrades to "hide module items"; the page-level hook
      // surfaces the real error. Keep null so a retry can happen.
      installedState = { modules: installedState.modules };
    })
    .finally(() => {
      installedPromise = null;
      emit();
    });
  return installedPromise;
}

/** Refetch the install list (after any store action / sign-in change). */
export function invalidateInstalledModules(): Promise<void> {
  installedState = { modules: installedState.modules };
  return fetchInstalled();
}

/** Test helper - clear the module-level cache between specs. */
export function __resetInstalledModules(): void {
  installedState = { modules: null };
  installedPromise = null;
}

export interface UseInstalledModulesResult {
  /** True once the first fetch resolved (menu shows nothing module-gated before). */
  ready: boolean;
  /** ACTIVE for this tenant? INACTIVE and not-installed are both false (plan 08 §5). */
  isActive: (name: string) => boolean;
}

export function useInstalledModules(): UseInstalledModulesResult {
  const { status } = useSession();
  const state = useSyncExternalStore(
    useCallback((cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    }, []),
    () => installedState,
    () => installedState,
  );

  useEffect(() => {
    if (status === 'authenticated' && state.modules === null) void fetchInstalled();
  }, [status, state.modules]);

  return useMemo(() => {
    const active = new Set(
      (state.modules ?? []).filter((m) => m.status === 'ACTIVE').map((m) => m.module),
    );
    return {
      ready: state.modules !== null,
      isActive: (name: string) => active.has(name),
    };
  }, [state.modules]);
}

/* ───────────────────── storefront / console hook ───────────────────── */

export interface UseAppStoreResult {
  modules: StoreModule[];
  loading: boolean;
  error: string | null;
  /** Module name with an in-flight action (disables that card's buttons). */
  pending: string | null;
  refresh: () => Promise<void>;
  /** install | deactivate | reactivate | update. */
  run: (name: string, action: StoreAction) => Promise<boolean>;
  /** Typed-confirmation wipe - `confirmName` must equal the module name. */
  uninstall: (name: string, confirmName: string) => Promise<boolean>;
}

export function useAppStore(tenantId?: string): UseAppStoreResult {
  const { update } = useSession();
  const [modules, setModules] = useState<StoreModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const fetchCatalog = useCallback(
    () => (tenantId ? appStoreService.catalogForTenant(tenantId) : appStoreService.catalog()),
    [tenantId],
  );

  const refresh = useCallback(async () => {
    try {
      const data = await fetchCatalog();
      if (!mounted.current) return;
      setModules(data);
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : 'Failed to load the App Store.');
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [fetchCatalog]);

  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [refresh]);

  /** Acting on the OWN tenant changes the acting admin's grants → refresh session + menu (D7). */
  const settle = useCallback(async () => {
    // Independent refreshes - run them concurrently (review: no ordering need).
    await Promise.all([
      refresh(),
      ...(tenantId ? [] : [invalidateInstalledModules(), update()]),
    ]);
  }, [refresh, tenantId, update]);

  const run = useCallback(
    async (name: string, action: StoreAction) => {
      setPending(name);
      setError(null);
      try {
        if (tenantId) await appStoreService.actForTenant(tenantId, name, action);
        else await appStoreService.act(name, action);
        await settle();
        return true;
      } catch (e) {
        if (mounted.current)
          setError(e instanceof Error ? e.message : 'The action failed. Please try again.');
        return false;
      } finally {
        if (mounted.current) setPending(null);
      }
    },
    [tenantId, settle],
  );

  const uninstall = useCallback(
    async (name: string, confirmName: string) => {
      setPending(name);
      setError(null);
      try {
        if (tenantId) await appStoreService.uninstallForTenant(tenantId, name, confirmName);
        else await appStoreService.uninstall(name, confirmName);
        await settle();
        return true;
      } catch (e) {
        if (mounted.current)
          setError(e instanceof Error ? e.message : 'Uninstall failed. Please try again.');
        return false;
      } finally {
        if (mounted.current) setPending(null);
      }
    },
    [tenantId, settle],
  );

  return { modules, loading, error, pending, refresh, run, uninstall };
}
