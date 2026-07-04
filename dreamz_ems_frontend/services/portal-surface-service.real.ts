/**
 * Real portal surface service (Cluster E, slice 0b). Hits the Profile-authed
 * `GET /portal/surfaces` via the PORTAL api-client (never the staff session).
 */
import { portalApiFetch } from '@/lib/portal-api-client';
import type {
  PortalSurface,
  PortalSurfaceService,
} from './portal-surface-service';

export const realPortalSurfaceService: PortalSurfaceService = {
  async listSurfaces(token?: string | null) {
    return portalApiFetch<PortalSurface[]>('/portal/surfaces', { token });
  },
};
