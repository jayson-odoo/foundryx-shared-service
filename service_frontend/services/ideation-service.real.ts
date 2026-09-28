/**
 * Real ideation service - talks to the FastAPI shared-service via the shared
 * api-client (plan: documentation/plans/ideation/, Phase A - Slice 8 wiring).
 *
 * Endpoint map (backend slices 2-7):
 * - listProducts  → GET  /products               (core catalog; unified Product)
 * - listIdeas     → GET  /ideation/ideas         (bare IdeaOut[], newest-first)
 * - getIdea       → GET  /ideation/ideas/{id}
 * - setStatus     → POST /ideation/ideas/{id}/status  {status}
 * - vote          → POST /ideation/ideas/{id}/vote    {dir}
 * - reorderPriority → PUT /ideation/ideas/reorder     {orderedIds}
 * - remove        → DELETE /ideation/ideas/{id}       (204)
 *
 * Contract deltas vs the Phase-1 mock (documented, FE adjusted to the real BE -
 * we do NOT fork logic):
 * - listProducts reads the CORE catalog (`GET /products`), the unified Product
 *   source (kind `software`|`goods`). `productDomainBase` is NOT merged here: it
 *   lives behind `GET /ideation/products/{id}/delivery` (gated
 *   `ideation.products.manage`), so eagerly merging it would (a) 403 for
 *   non-Maintainers and (b) cost an N+1 the list/board/form never render. It is
 *   left undefined; a delivery-config surface fetches it on demand.
 * - createIdea → POST /ideation/ideas (operator surface, gated
 *   `ideation.ideas.submit`) - distinct from the conversational WhatsApp intake
 *   (`POST /ideation/intake/create-idea`, workspace-key server-to-server). No
 *   draft/collect/confirm gate: an operator typing an idea IS deliberate, so it
 *   is created straight into `captured` with the operator as submitter.
 * - updateIdea → PATCH /ideation/ideas/{id} (gated `ideation.triage.manage`) -
 *   edits productId / problem / rawText. A `status` field is routed through
 *   setStatus (POST /{id}/status) instead - the edit route never moves status.
 * - Attachments on create are NOT persisted yet (idea_attachments writer is a
 *   later slice); the field is accepted by the FE input but dropped here.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Board,
  Idea,
  IdeaClusterSuggestions,
  Product,
} from '@/types/ideation';
import type { IdeaCreateInput, IdeaExtendedOps, IdeaService } from './ideation-service';

/** Core catalog list envelope (app/schemas/catalog.py → ListResponse). */
interface CoreProductRow {
  id: string;
  name: string;
  kind: string;
}
interface CoreProductList {
  items: CoreProductRow[];
  total: number;
  page: number;
  pageSize: number;
}

/** The FE Product.kind is a 2-value union; core kinds are open - coerce. */
function toProductKind(kind: string): Product['kind'] {
  return kind === 'software' ? 'software' : 'goods';
}

const idea = (id: string) => `/ideation/ideas/${encodeURIComponent(id)}`;

export const realIdeationService: IdeaService & IdeaExtendedOps = {
  async listProducts(): Promise<Product[]> {
    const res = await apiFetch<CoreProductList>('/products?page_size=200');
    return res.items.map((p) => ({
      id: p.id,
      name: p.name,
      kind: toProductKind(p.kind),
      productDomainBase: null,
    }));
  },

  listIdeas(opts?: { includeTest?: boolean }): Promise<Idea[]> {
    const q = opts?.includeTest ? '?includeTest=true' : '';
    return apiFetch<Idea[]>(`/ideation/ideas${q}`);
  },

  getIdea(id: string): Promise<Idea> {
    return apiFetch<Idea>(idea(id));
  },

  // Operator-facing create (distinct from the workspace-key WhatsApp intake).
  // Attachments are not persisted yet (later slice) - the field is dropped here.
  createIdea(input: IdeaCreateInput): Promise<Idea> {
    return apiFetch<Idea>('/ideation/ideas', {
      method: 'POST',
      body: JSON.stringify({
        productId: input.productId,
        problem: input.problem,
        proposedSolution: input.proposedSolution ?? '',
        impact: input.impact ?? '',
        department: input.department ?? '',
        rawText: input.rawText,
      }),
    });
  },
  // Operator-facing edit. The PATCH route is fields-only - a save never moves
  // status any more (issue #94, ideation round 2, AC-94-34: the form dropped
  // its Status control entirely, owner Q5). Any extra key on `input` (e.g. a
  // stale caller still shaped like the old status-carrying payload) is simply
  // not a recognised field and is ignored.
  async updateIdea(id: string, input: Partial<IdeaCreateInput>): Promise<Idea> {
    const { attachments, ...fields } = input;
    void attachments;
    const patch: Record<string, unknown> = {};
    if (fields.productId !== undefined) patch.productId = fields.productId;
    if (fields.problem !== undefined) patch.problem = fields.problem;
    if (fields.proposedSolution !== undefined) patch.proposedSolution = fields.proposedSolution;
    if (fields.impact !== undefined) patch.impact = fields.impact;
    if (fields.department !== undefined) patch.department = fields.department;
    if (fields.rawText !== undefined) patch.rawText = fields.rawText;
    return Object.keys(patch).length > 0
      ? apiFetch<Idea>(idea(id), { method: 'PATCH', body: JSON.stringify(patch) })
      : apiFetch<Idea>(idea(id));
  },

  // `toStatusId` (AC-94-53) - the backend's `StatusIn` schema accepts either
  // this engine target id OR the legacy lifecycle KEY (the deferred Archive
  // handler's shape) under the same `status` wire key.
  setStatus(id: string, toStatusId: string): Promise<Idea> {
    return apiFetch<Idea>(`${idea(id)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: toStatusId }),
    });
  },

  vote(id: string, dir: 'up' | 'down'): Promise<Idea> {
    return apiFetch<Idea>(`${idea(id)}/vote`, {
      method: 'POST',
      body: JSON.stringify({ dir }),
    });
  },

  reorderPriority(orderedIds: string[]): Promise<Idea[]> {
    return apiFetch<Idea[]>('/ideation/ideas/reorder', {
      method: 'PUT',
      body: JSON.stringify({ orderedIds }),
    });
  },

  suggestClusters(productId?: string): Promise<IdeaClusterSuggestions> {
    const q = productId ? `?productId=${encodeURIComponent(productId)}` : '';
    return apiFetch<IdeaClusterSuggestions>(`/ideation/ideas/clusters${q}`);
  },

  async remove(id: string): Promise<void> {
    await apiFetch<void>(idea(id), { method: 'DELETE' });
  },

  // Merge / unmerge (issue #94, ideation round 2, plan section 3.3). Static
  // paths declared before `/{idea_id}` on the backend (the existing ordering
  // rule) so `/merge` never collides with a dynamic id segment.
  merge(survivorId: string, ideaIds: string[]): Promise<Idea> {
    return apiFetch<Idea>('/ideation/ideas/merge', {
      method: 'POST',
      body: JSON.stringify({ survivorId, ideaIds }),
    });
  },

  unmerge(id: string): Promise<Idea[]> {
    return apiFetch<Idea[]>(`${idea(id)}/unmerge`, { method: 'POST' });
  },

  listMerged(id: string): Promise<Idea[]> {
    return apiFetch<Idea[]>(`${idea(id)}/merged`);
  },

  getBoard(opts?: { includeTest?: boolean; productId?: string }): Promise<Board> {
    const params = new URLSearchParams();
    if (opts?.includeTest) params.set('includeTest', 'true');
    if (opts?.productId) params.set('productId', opts.productId);
    const qs = params.toString();
    return apiFetch<Board>(`/ideation/ideas/board${qs ? `?${qs}` : ''}`);
  },
};
