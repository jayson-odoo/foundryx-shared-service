/**
 * Ideation embed service - the chrome-less iframe's data boundary, authenticated
 * by the short-lived EMBED token (NOT a NextAuth session): the token is placed in
 * `embedAuthStore` by the embed session gate, and `lib/api-client` attaches it as
 * the Bearer + never `signOut()`s on a 401 (a 401 is a clean expiry, handled by
 * the silent re-mint handshake).
 *
 * WS-C / AC-CAP-9..13 - FULL operator-grid parity: this object implements the
 * SAME `IdeaService` interface the operator surface uses (so ONE component set
 * serves both modes), but every call hits the `/embed/*` routes. The backend
 * scopes every read/write to the token's tenant AND product, so the iframe can
 * neither read nor mutate another tenant/product (server-authoritative).
 *
 * Enforced layering: UI → hooks → this service → lib/api-client → FastAPI.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Board,
  Idea,
  IdeaClusterSuggestions,
  Product,
} from '@/types/ideation';
import type { IdeaCreateInput, IdeaExtendedOps, IdeaService } from './ideation-service';

export interface EmbedTokenScope {
  tenant_id: string;
  connection_id: string;
  idea_id: string | null;
  /** The connection's product scope (WS-C). `null` for an unscoped connection. */
  product_id: string | null;
  scope: string;
}

// Cached from the last `validateToken` so `listProducts` can surface the
// connection's single scoped product for the create/edit form picker (there is
// no `/embed/products` - the product is fixed by the token server-side).
let lastScope: EmbedTokenScope | null = null;

const embedIdea = (id: string) => `/embed/ideas/${encodeURIComponent(id)}`;

export const ideationEmbedService: IdeaService &
  IdeaExtendedOps & {
    validateToken(token: string): Promise<EmbedTokenScope>;
  } = {
  /** Verify the embed token → its tenant + product scope (render-vs-expired gate). */
  async validateToken(token: string): Promise<EmbedTokenScope> {
    const scope = await apiFetch<EmbedTokenScope>('/embed/validate', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
    lastScope = scope;
    return scope;
  },

  /**
   * The connection's product(s). The embed is product-scoped server-side, so this
   * surfaces the ONE scoped product (id from the token; name resolved from any
   * existing idea, else a generic label) - enough for the capture/edit picker,
   * which the backend overrides anyway. An unscoped connection derives the
   * distinct products from the visible ideas.
   */
  async listProducts(): Promise<Product[]> {
    const ideas = await ideationEmbedService.listIdeas();
    const productId = lastScope?.product_id ?? null;
    if (productId) {
      const match = ideas.find((i) => i.productId === productId);
      return [
        {
          id: productId,
          name: match?.productName ?? 'This product',
          kind: 'software',
          productDomainBase: null,
        },
      ];
    }
    const seen = new Map<string, Product>();
    for (const i of ideas) {
      if (!seen.has(i.productId)) {
        seen.set(i.productId, {
          id: i.productId,
          name: i.productName,
          kind: 'software',
          productDomainBase: null,
        });
      }
    }
    return Array.from(seen.values());
  },

  /** Product-scoped ideas for the token (backend enforces scope). `filter`
   * (AC-94-60) - `/embed/ideas` accepts the same `active|archived|all` scope
   * as the operator route (no `includeTest` there - the embed session never
   * carries a test lane); the list and the record pager pass `'all'` so
   * Archived is fed, split client side by `statusIsArchived`. */
  listIdeas(opts?: { filter?: 'active' | 'archived' | 'all' }): Promise<Idea[]> {
    const q = opts?.filter ? `?filter=${encodeURIComponent(opts.filter)}` : '';
    return apiFetch<Idea[]>(`/embed/ideas${q}`);
  },

  /** One idea by id, scoped to the token's tenant + product (404 outside it). */
  getIdea(id: string): Promise<Idea> {
    return apiFetch<Idea>(embedIdea(id));
  },

  /** Create an idea - the backend FORCES the connection's product (the body
   * `productId` is ignored server-side). */
  createIdea(input: IdeaCreateInput): Promise<Idea> {
    return apiFetch<Idea>('/embed/ideas', {
      method: 'POST',
      body: JSON.stringify({
        problem: input.problem,
        proposedSolution: input.proposedSolution ?? '',
        impact: input.impact ?? '',
        department: input.department ?? '',
        rawText: input.rawText,
      }),
    });
  },

  /** Edit the mutable fields. Product is NOT reassignable via the embed; a
   * save never moves status any more (AC-94-34 - the form dropped its Status
   * control entirely, owner Q5). */
  async updateIdea(id: string, input: Partial<IdeaCreateInput>): Promise<Idea> {
    const { attachments, productId, ...fields } = input;
    void attachments;
    void productId; // embed never reassigns the product (scope integrity)
    const patch: Record<string, unknown> = {};
    if (fields.problem !== undefined) patch.problem = fields.problem;
    if (fields.proposedSolution !== undefined) patch.proposedSolution = fields.proposedSolution;
    if (fields.impact !== undefined) patch.impact = fields.impact;
    if (fields.department !== undefined) patch.department = fields.department;
    if (fields.rawText !== undefined) patch.rawText = fields.rawText;
    return Object.keys(patch).length > 0
      ? apiFetch<Idea>(embedIdea(id), { method: 'PATCH', body: JSON.stringify(patch) })
      : apiFetch<Idea>(embedIdea(id));
  },

  // `toStatusId` (AC-94-53) - the backend's `StatusIn` schema accepts EXACTLY
  // ONE of `status` (legacy key) or `toStatusId` (this call's shape).
  setStatus(id: string, toStatusId: string): Promise<Idea> {
    return apiFetch<Idea>(`${embedIdea(id)}/status`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },

  vote(id: string, dir: 'up' | 'down'): Promise<Idea> {
    return apiFetch<Idea>(`${embedIdea(id)}/vote`, {
      method: 'POST',
      body: JSON.stringify({ dir }),
    });
  },

  reorderPriority(orderedIds: string[]): Promise<Idea[]> {
    return apiFetch<Idea[]>('/embed/ideas/reorder', {
      method: 'PUT',
      body: JSON.stringify({ orderedIds }),
    });
  },

  /** The chrome-less embed never offers clustering (operator-only, gated by
   * `ideation.clusters.manage`) - a no-op keeps the shared `IdeaService`
   * contract satisfied. */
  async suggestClusters(): Promise<IdeaClusterSuggestions> {
    return { clusters: [], degraded: false };
  },

  async remove(id: string): Promise<void> {
    await apiFetch<void>(embedIdea(id), { method: 'DELETE' });
  },

  // Merge / unmerge parity (AC-94-16) - every id the backend resolves stays
  // scoped to the token's tenant AND product, same as every other embed route.
  merge(survivorId: string, ideaIds: string[]): Promise<Idea> {
    return apiFetch<Idea>('/embed/ideas/merge', {
      method: 'POST',
      body: JSON.stringify({ survivorId, ideaIds }),
    });
  },

  unmerge(id: string): Promise<Idea[]> {
    return apiFetch<Idea[]>(`${embedIdea(id)}/unmerge`, { method: 'POST' });
  },

  listMerged(id: string): Promise<Idea[]> {
    return apiFetch<Idea[]>(`${embedIdea(id)}/merged`);
  },

  getBoard(opts?: { includeTest?: boolean; productId?: string }): Promise<Board> {
    const q = opts?.includeTest ? '?includeTest=true' : '';
    return apiFetch<Board>(`/embed/board${q}`);
  },
};
