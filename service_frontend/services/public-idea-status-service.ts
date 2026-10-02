/**
 * Public (pre-auth) idea-status service (S5) - NO auth, the `status_token`
 * itself is the capability. Mirrors `public-share-service.ts`: resolve
 * returns the view (uniform 404 -> null), rethrows any other failure.
 */
import { ApiError, publicFetch } from '@/lib/api-client';
import type { PublicIdeaStatus } from '@/types/ideation';

export interface PublicIdeaStatusService {
  resolve(token: string): Promise<PublicIdeaStatus | null>;
}

export const publicIdeaStatusService: PublicIdeaStatusService = {
  async resolve(token) {
    try {
      return await publicFetch<PublicIdeaStatus>(`/public/ideas/${encodeURIComponent(token)}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
};
