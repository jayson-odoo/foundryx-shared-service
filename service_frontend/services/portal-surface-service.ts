/**
 * Portal surface service (Cluster E, slice 0b — AC-06-24/25). The boundary the
 * portal unified dashboard + nav talk to (via use-portal-surfaces). The backend
 * already gates by portal-permission key, so the response IS the visible set.
 *
 * Layering: portal UI → hook → service → portal-api-client → FastAPI.
 *   GET /portal/surfaces → PortalSurface[] (each with its scoped contexts)
 *
 * Phase B binds the REAL impl (bottom). The mock is retained for Vitest.
 */
import { realPortalSurfaceService } from './portal-surface-service.real';

/** A scoped membership context a surface's data is narrowed to (AC-06-24). */
export interface PortalSurfaceContext {
  /** 'tenant' (tenant-wide) | 'project' (a single event). */
  scopeType: string;
  /** The scope record id (e.g. a project/event id); null for tenant scope. */
  scopeId: string | null;
  /** The real event/project name (AC-06-25) — server-resolved; null for tenant
   * scope or an unresolvable id (the FE falls back to a generic label). */
  label?: string | null;
}

/** One accessible portal surface (a dashboard section + nav item). */
export interface PortalSurface {
  key: string;
  label: string;
  gatingPermission: string;
  module: string;
  sortOrder: number;
  description: string | null;
  /** The Profile's contexts for this surface (memberships granting its key). */
  contexts: PortalSurfaceContext[];
}

export interface PortalSurfaceService {
  /** The Profile's visible surfaces + per-surface scoped contexts. */
  listSurfaces(token?: string | null): Promise<PortalSurface[]>;
}

// Phase B swap — mock retained in portal-surface-service.mock.ts for tests.
export const portalSurfaceService: PortalSurfaceService =
  realPortalSurfaceService;
