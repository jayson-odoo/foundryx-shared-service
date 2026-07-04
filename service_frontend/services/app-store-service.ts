/**
 * App Store service (plan 08) — the boundary the storefront + console Modules
 * tab talk to (via use-app-store). Phase A binds the mock; Phase B swaps to the
 * real api-client impl in ONE line (bottom of file). The interface IS the
 * backend contract (plan 08 §7): tenant-side `/app-store/*` (app_store.* core
 * perms) and operator-side `/platform/tenants/{id}/modules/*`
 * (tenants.manage_modules, platform guard) — same shapes, two entry points.
 */
import type { InstalledModule, StoreAction, StoreModule } from '@/types/app-store';
import { realAppStoreService } from './app-store-service.real';

export interface AppStoreService {
  /** Listed modules + the CALLER's tenant state (GET /app-store/modules). */
  catalog(): Promise<StoreModule[]>;
  /** Lightweight install list for menu gating (perm-free GET /me/modules). */
  installed(): Promise<InstalledModule[]>;
  /** install | deactivate | reactivate | update for the caller's tenant. */
  act(name: string, action: StoreAction): Promise<StoreModule>;
  /** Typed-confirmation wipe: `confirmName` must equal the module name (plan 08 §5). */
  uninstall(name: string, confirmName: string): Promise<void>;

  /** Operator (console Modules tab) — same shapes against any tenant. */
  catalogForTenant(tenantId: string): Promise<StoreModule[]>;
  actForTenant(tenantId: string, name: string, action: StoreAction): Promise<StoreModule>;
  uninstallForTenant(tenantId: string, name: string, confirmName: string): Promise<void>;
}

// Phase B swap done — mock retained in app-store-service.mock.ts for tests.
export const appStoreService: AppStoreService = realAppStoreService;
