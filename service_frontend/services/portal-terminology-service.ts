/**
 * Portal terminology service boundary (Cluster E portal-signout fix, sprint-4/06).
 *
 * The Profile portal review surfaces need the tenant's terminology labels, but
 * the staff `terminology-service` reaches them through the STAFF `apiFetch` and
 * the staff-only `GET /terminology` (rejects a Profile JWT 401 → portal signout).
 * This boundary hits the Profile-authed `GET /portal/terminology` through the
 * PORTAL api-client — the `(portal)` tree must NEVER invoke the staff client.
 *
 * Layering: portal UI → use-portal-terminology → THIS service → portal-api-client.
 */
import type { TerminologyMap } from '@/types/terminology';
import { realPortalTerminologyService } from './portal-terminology-service.real';

export interface PortalTerminologyService {
  /** Merged map (defaults ⊕ tenant overrides) for the Profile's tenant. */
  getTerminology(token?: string | null): Promise<TerminologyMap>;
}

export const portalTerminologyService: PortalTerminologyService =
  realPortalTerminologyService;
