/**
 * Operator: followers + read-only share link of one feedback item (lane
 * FEEDBACK-SUBSCRIBE). Staff session (NextAuth bearer) via `apiFetch`.
 */
import { apiFetch } from '@/lib/api-client';
import type { IdeaFollower } from '@/types/ideation';
import type { HistoryEntry } from '@/types/record-history';

const base = (ideaId: string) => `/ideation/ideas/${encodeURIComponent(ideaId)}`;

export const ideaFollowerService = {
  list(ideaId: string): Promise<IdeaFollower[]> {
    return apiFetch<IdeaFollower[]>(`${base(ideaId)}/followers`);
  },
  add(ideaId: string, contactId: string): Promise<IdeaFollower[]> {
    return apiFetch<IdeaFollower[]>(`${base(ideaId)}/followers`, {
      method: 'POST',
      body: JSON.stringify({ contactId }),
    });
  },
  remove(ideaId: string, contactId: string): Promise<void> {
    return apiFetch<void>(`${base(ideaId)}/followers/${encodeURIComponent(contactId)}`, { method: 'DELETE' });
  },
  shareLink(ideaId: string): Promise<{ url: string }> {
    return apiFetch<{ url: string }>(`${base(ideaId)}/share-link`, { method: 'POST' });
  },
  /** The item's History tab (who, on behalf of, when, action, old -> new). */
  history(ideaId: string): Promise<HistoryEntry[]> {
    return apiFetch<HistoryEntry[]>(`${base(ideaId)}/history`);
  },
  stopSharing(ideaId: string): Promise<void> {
    return apiFetch<void>(`${base(ideaId)}/share-link`, { method: 'DELETE' });
  },
};
