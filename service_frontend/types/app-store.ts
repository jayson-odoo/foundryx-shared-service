/**
 * App Store types (plan 08) - per-tenant module lifecycle. The catalog is
 * global (synced from on-disk manifests); install state is per tenant
 * (`tenant_modules`). Code is global - "update" provisions the tenant's DATA
 * to the current code version (D3/D4: version gating, never code pinning).
 */

/** Per-tenant install status - code branches only on these. */
export type ModuleStatus = 'ACTIVE' | 'INACTIVE';

/** Lifecycle actions sharing one POST shape (uninstall is separate - typed confirm). */
export type StoreAction = 'install' | 'deactivate' | 'reactivate' | 'update';

/** Catalog entry + the viewing tenant's install state (GET /app-store/modules). */
export interface StoreModule {
  /** manifest `module_name` - the API identity. */
  name: string;
  title: string;
  description: string;
  icon: string | null;
  /** Current CODE version (manifest) - global for all tenants. */
  version: string;
  /** null = not installed for this tenant. */
  status: ModuleStatus | null;
  /** What this tenant is provisioned at - gates features (D4). */
  installedVersion: string | null;
  /** True when `version` > `installedVersion` (server-computed). */
  updateAvailable: boolean;
  installedAt: string | null; // ISO
  /** Module platform v2 (plan sprint-3/10) - declared deps + capabilities. */
  requires?: { name: string; version?: string }[];
  optional?: { name: string; version?: string }[];
  provides?: { capability: string; version: number }[];
  /** A module that failed to load at boot (self-disabled; not installable). */
  errored?: boolean;
  errorMessage?: string | null;
  /** False when this module's hard requires aren't met for the tenant. */
  availabilityOk?: boolean;
}

/** Lightweight row for menu gating (GET /app-store/installed). */
export interface InstalledModule {
  module: string;
  status: ModuleStatus;
  version: string;
}

/** Display state for the storefront StatusBadge (derived, not stored). */
export type StoreModuleBadge = 'NOT_INSTALLED' | 'ACTIVE' | 'INACTIVE' | 'UPDATE_AVAILABLE';

export function moduleBadge(m: StoreModule): StoreModuleBadge {
  if (m.status === null) return 'NOT_INSTALLED';
  if (m.status === 'INACTIVE') return 'INACTIVE';
  return m.updateAvailable ? 'UPDATE_AVAILABLE' : 'ACTIVE';
}
