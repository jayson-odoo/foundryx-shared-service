/**
 * Ideation embed service — the chrome-less iframe page's data boundary
 * (PLAN-ideation-embed-sso §9, AC-E-8/9). Talks to the shared-service embed
 * endpoints, authenticated by the short-lived EMBED token (NOT a NextAuth
 * session): the token is placed in `embedAuthStore` by the embed page, and
 * `lib/api-client` attaches it as the Bearer + never `signOut()`s on a 401
 * (there is no NextAuth session in the iframe — a 401 is a clean expiry).
 *
 * The reads hit the tenant-SCOPED embed endpoints (`/embed/ideas`), whose tenant
 * comes from the token server-side — a token for tenant A can never read tenant
 * B (AC-E-8/12). The idea shape returned is identical to `/ideation/ideas`, so no
 * mapping logic is forked here.
 *
 * Enforced layering: UI → this service → lib/api-client → FastAPI.
 */
import { apiFetch } from '@/lib/api-client';
import type { Idea } from '@/types/ideation';

export interface EmbedTokenScope {
  tenant_id: string;
  connection_id: string;
  idea_id: string | null;
  scope: string;
}

export const ideationEmbedService = {
  /** Verify the embed token → its tenant scope (render-vs-expired gate). */
  validateToken(token: string): Promise<EmbedTokenScope> {
    return apiFetch<EmbedTokenScope>('/embed/validate', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  },

  /** All ideas visible to the token's tenant, newest first (read-only). */
  listIdeas(): Promise<Idea[]> {
    return apiFetch<Idea[]>('/embed/ideas');
  },

  /** One idea by id, scoped to the token's tenant (404 if outside it). */
  getIdea(id: string): Promise<Idea> {
    return apiFetch<Idea>(`/embed/ideas/${encodeURIComponent(id)}`);
  },
};
