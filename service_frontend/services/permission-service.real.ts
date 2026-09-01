/**
 * Real permission service (Phase B) - `GET /permissions` returns the synced
 * catalog grouped by resource. Bound in one line from permission-service.ts when
 * the backend lands.
 */
import { apiFetch } from '@/lib/api-client';
import type { PermissionCatalog } from '@/types/permission';
import type { PermissionService } from './permission-service';

export const realPermissionService: PermissionService = {
  catalog() {
    return apiFetch<PermissionCatalog>('/permissions');
  },
};
