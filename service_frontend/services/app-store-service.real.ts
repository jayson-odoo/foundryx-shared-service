/**
 * Real App Store service (Phase B) - talks to FastAPI via the shared
 * api-client. Backend returns camelCase matching the app-store types, so no
 * field remapping. Bound in one line from app-store-service.ts when the
 * backend lands (plan 08 §7 endpoints).
 */
import { apiFetch } from '@/lib/api-client';
import type { InstalledModule, StoreAction, StoreModule } from '@/types/app-store';
import type { AppStoreService } from './app-store-service';

export const realAppStoreService: AppStoreService = {
  catalog() {
    return apiFetch<StoreModule[]>('/app-store/modules');
  },
  installed() {
    // Menu gating only - perm-free /me/modules (NOT /app-store/installed, which
    // needs app_store.read). Decouples seeing a module's sidebar item from
    // holding App Store read. Same shape; store/console use catalog() instead.
    return apiFetch<InstalledModule[]>('/me/modules');
  },
  act(name: string, action: StoreAction) {
    return apiFetch<StoreModule>(`/app-store/modules/${name}/${action}`, { method: 'POST' });
  },
  uninstall(name: string, confirmName: string) {
    return apiFetch<void>(`/app-store/modules/${name}/uninstall`, {
      method: 'POST',
      body: JSON.stringify({ confirmName }),
    });
  },
  catalogForTenant(tenantId: string) {
    return apiFetch<StoreModule[]>(`/platform/tenants/${tenantId}/modules`);
  },
  actForTenant(tenantId: string, name: string, action: StoreAction) {
    return apiFetch<StoreModule>(`/platform/tenants/${tenantId}/modules/${name}/${action}`, {
      method: 'POST',
    });
  },
  uninstallForTenant(tenantId: string, name: string, confirmName: string) {
    return apiFetch<void>(`/platform/tenants/${tenantId}/modules/${name}/uninstall`, {
      method: 'POST',
      body: JSON.stringify({ confirmName }),
    });
  },
};
