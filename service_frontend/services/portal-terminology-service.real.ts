/** Real portal terminology service — Profile session via the PORTAL api-client. */
import type { TerminologyMap } from '@/types/terminology';
import { portalApiFetch } from '@/lib/portal-api-client';
import type { PortalTerminologyService } from './portal-terminology-service';

export const realPortalTerminologyService: PortalTerminologyService = {
  getTerminology(token?: string | null) {
    return portalApiFetch<TerminologyMap>('/portal/terminology', { token });
  },
};
