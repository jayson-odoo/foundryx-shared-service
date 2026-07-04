'use client';

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import type {
  BrandingAssetKind,
  PublicBranding,
  TenantBranding,
  UpdateBrandingInput,
} from '@/types/branding';
import { deriveTenantSlug } from '@/lib/tenant';
import { brandingService } from '@/services/branding-service';

/**
 * Branding hooks (sprint-2/03).
 *
 * `useBrandingAdmin(tenantId?)` — the editor state machine. Omit `tenantId`
 * for the caller's own tenant (/settings/branding); pass one to act on ANOTHER
 * tenant via the operator endpoints (console Branding tab).
 *
 * `useTenantBranding()` — the CURRENT HOST's public branding for consumption
 * surfaces (sign-in panel, sidebar logo, tab title/favicon, theme provider).
 * Module-level store so the shell doesn't refetch per render; own-tenant edits
 * call `refreshTenantBranding()` so every surface updates immediately.
 */

/* ─────────────── public-branding store (consumption surfaces) ─────────────── */

const UNBRANDED: PublicBranding = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};

type PublicState = {
  /** null until the first fetch resolves (avoids a FoundryX→tenant flash where possible). */
  branding: PublicBranding | null;
};

let publicState: PublicState = { branding: null };
let publicPromise: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

function currentSlug(): string {
  return typeof window === 'undefined'
    ? 'default'
    : deriveTenantSlug(window.location.hostname);
}

function fetchPublicBranding(): Promise<void> {
  publicPromise ??= brandingService
    .publicBranding(currentSlug())
    .then((branding) => {
      publicState = { branding };
    })
    .catch(() => {
      // Consumption surfaces degrade to FoundryX defaults — never block render.
      publicState = { branding: publicState.branding ?? UNBRANDED };
    })
    .finally(() => {
      publicPromise = null;
      emit();
    });
  return publicPromise;
}

/** Re-pull the host's public branding (after an own-tenant branding mutation). */
export function refreshTenantBranding(): Promise<void> {
  publicState = { branding: publicState.branding }; // keep last good while refetching
  return fetchPublicBranding();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (publicState.branding === null) void fetchPublicBranding();
  return () => listeners.delete(listener);
}

const getSnapshot = (): PublicState => publicState;
const getServerSnapshot = (): PublicState => ({ branding: null });

export interface UseTenantBrandingResult {
  /** Resolved branding — FoundryX defaults while loading / when unbranded. */
  branding: PublicBranding;
  /** True once the first fetch resolved (gate flash-sensitive swaps on this). */
  isResolved: boolean;
}

export function useTenantBranding(): UseTenantBrandingResult {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return {
    branding: state.branding ?? UNBRANDED,
    isResolved: state.branding !== null,
  };
}

/* ────────────────────────── editor (admin) hook ────────────────────────── */

export interface UseBrandingAdminResult {
  branding: TenantBranding | null;
  isLoading: boolean;
  error: string | null;
  /** Save slogan + tokens. Rejects with a user-renderable message on failure. */
  save(input: UpdateBrandingInput): Promise<TenantBranding>;
  upload(kind: BrandingAssetKind, file: File): Promise<TenantBranding>;
  removeAsset(kind: BrandingAssetKind): Promise<TenantBranding>;
}

export function useBrandingAdmin(tenantId?: string): UseBrandingAdminResult {
  const [branding, setBranding] = useState<TenantBranding | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setError(null);
    brandingService
      .get(tenantId)
      .then((b) => active && setBranding(b))
      .catch(
        (e) =>
          active &&
          setError(e instanceof Error ? e.message : 'Could not load branding.'),
      )
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [tenantId]);

  /** Own-tenant mutations also refresh the host's consumption surfaces. */
  const settle = useCallback(
    (updated: TenantBranding): TenantBranding => {
      setBranding(updated);
      if (!tenantId) void refreshTenantBranding();
      return updated;
    },
    [tenantId],
  );

  const run = useCallback(
    async (op: Promise<TenantBranding>): Promise<TenantBranding> =>
      settle(await op),
    [settle],
  );

  const save = useCallback(
    (input: UpdateBrandingInput) =>
      run(brandingService.update(input, tenantId)),
    [run, tenantId],
  );
  const upload = useCallback(
    (kind: BrandingAssetKind, file: File) =>
      run(brandingService.uploadAsset(kind, file, tenantId)),
    [run, tenantId],
  );
  const removeAsset = useCallback(
    (kind: BrandingAssetKind) =>
      run(brandingService.removeAsset(kind, tenantId)),
    [run, tenantId],
  );

  return { branding, isLoading, error, save, upload, removeAsset };
}
