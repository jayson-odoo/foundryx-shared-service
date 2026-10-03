/**
 * Public (pre-auth) idea-status service (S5) - NO auth, the `status_token`
 * itself is the capability. Mirrors `public-share-service.ts`: resolve
 * returns the view (uniform 404 -> null), rethrows any other failure.
 */
import { ApiError, publicFetch } from '@/lib/api-client';
import type { IdeaComment, PublicIdeaStatus } from '@/types/ideation';

export interface PublicIdeaStatusService {
  resolve(token: string): Promise<PublicIdeaStatus | null>;
  /** The status page's comment thread (plan 19, AC-19-33), oldest first. */
  listComments(token: string): Promise<IdeaComment[]>;
  /** Post a visitor comment. The author name is derived server side - never sent. */
  addComment(token: string, body: string, parentId?: string): Promise<IdeaComment>;
}

const commentsPath = (token: string) => `/public/ideas/${encodeURIComponent(token)}/comments`;

export const publicIdeaStatusService: PublicIdeaStatusService = {
  async resolve(token) {
    try {
      return await publicFetch<PublicIdeaStatus>(`/public/ideas/${encodeURIComponent(token)}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  listComments(token) {
    return publicFetch<IdeaComment[]>(commentsPath(token));
  },

  addComment(token, body, parentId) {
    return publicFetch<IdeaComment>(commentsPath(token), {
      method: 'POST',
      body: JSON.stringify(parentId ? { body, parentId } : { body }),
    });
  },
};
