/** Mock portal terminology service (Vitest) — returns a static merged map. */
import type { TerminologyMap } from '@/types/terminology';
import type { PortalTerminologyService } from './portal-terminology-service';

export const mockPortalTerminologyService: PortalTerminologyService = {
  async getTerminology(): Promise<TerminologyMap> {
    return {
      submission: { singular: 'Submission', plural: 'Submissions' },
      review: { singular: 'Review', plural: 'Reviews' },
    };
  },
};
