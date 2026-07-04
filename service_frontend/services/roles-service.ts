/**
 * Roles service — real api-client (Phase B). RBAC/permissions = backlog BL-009.
 */
import { apiFetch } from '@/lib/api-client';
import type { Role } from '@/types/user';

// Retained for the (now-unused) mock service + tests; not used at runtime.
export const MOCK_ROLES: Role[] = [
  { id: 'role-admin', name: 'Admin' },
  { id: 'role-event-manager', name: 'Event Manager' },
  { id: 'role-coordinator', name: 'Coordinator' },
  { id: 'role-vendor-manager', name: 'Vendor Manager' },
  { id: 'role-finance', name: 'Finance' },
  { id: 'role-member', name: 'Member' },
  { id: 'role-viewer', name: 'Viewer' },
];

export interface RolesService {
  list(): Promise<Role[]>;
}

export const rolesService: RolesService = {
  list() {
    // Lightweight (id, name) list for the user-form role picker. The paginated
    // /roles endpoint is the roles-management list; this is just the options.
    return apiFetch<Role[]>('/roles/options');
  },
};
