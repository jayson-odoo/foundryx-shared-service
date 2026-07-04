/**
 * Permission catalog service — the boundary the role form talks to (via the
 * form hook). Phase A binds the mock; Phase B swaps to the real api-client impl
 * in ONE line (bottom of file). The interface IS the backend contract.
 */
import type { PermissionCatalog } from '@/types/permission';
import { realPermissionService } from './permission-service.real';

export interface PermissionService {
  /** The full catalog (flat list of resources); UI groups by `module`. */
  catalog(): Promise<PermissionCatalog>;
}

// Phase B: real api-client. (Mock retained in permission-service.mock.ts for tests.)
export const permissionService: PermissionService = realPermissionService;
