/**
 * Ideation service - the boundary the UI talks to (plan: documentation/plans/
 * ideation/, Phase A). The interface IS the backend contract (§5.1: the
 * `create_idea` HTTP endpoint + idea reads). Phase-1 binds the in-memory MOCK
 * (swap is the ONE line at the bottom); Phase-2 will add `ideation-service.real.ts`
 * (apiFetch against shared-service) and bind it here.
 *
 * Enforced layering: UI → hooks → this service → lib/api-client → FastAPI.
 */
import type { Board, Idea, IdeaClusterSuggestions, Product } from '@/types/ideation';
import { realIdeationService } from './ideation-service.real';

/** Manual capture payload (the WhatsApp path fills the same fields via the tool). */
export interface IdeaCreateInput {
  productId: string;
  problem: string;
  /** Segregated intake fields (the WhatsApp path fills the same keys). */
  proposedSolution?: string;
  impact?: string;
  department?: string;
  rawText: string;
  /** Dropped attachments (Phase 1: metadata only; Phase 2 uploads the bytes). */
  attachments?: {
    kind: import('@/types/ideation').IdeaAttachmentKind;
    name: string;
    sizeBytes?: number;
  }[];
}

export interface IdeaService {
  /** All products an idea can target (software + goods). */
  listProducts(): Promise<Product[]>;
  /** All ideas, newest first. `includeTest` opts into console/`--say` test
   * ideas (issue #1179) - off by default. `filter` selects the backend's
   * active (default) / archived / all scope (AC-94-60) - the list and the
   * record pager always pass `'all'` so the shared `selectIdeaRows` can split
   * Active vs Archived client side by `statusIsArchived`; a bare call (e.g.
   * the BR "link ideas" candidate picker) keeps the server default
   * (active only). */
  listIdeas(opts?: { includeTest?: boolean; filter?: 'active' | 'archived' | 'all' }): Promise<Idea[]>;
  /** One idea by id (form view). Rejects if not found. */
  getIdea(id: string): Promise<Idea>;
  /** Update editable idea fields (form view save) - fields only, NEVER status
   * (issue #94, ideation round 2, AC-94-34: the form never moves status). */
  updateIdea(id: string, input: Partial<IdeaCreateInput>): Promise<Idea>;
  /** Manually create a captured idea (deterministic - no LLM at shared-service). */
  createIdea(input: IdeaCreateInput): Promise<Idea>;
  /** Move an idea along a status_engine edge - `toStatusId` is the target
   * status row id (AC-94-53); the legacy lifecycle KEY form still works for
   * the deferred Archive handler. */
  setStatus(id: string, toStatusId: string): Promise<Idea>;
  /** Toggle the current user's vote (one per user): click same dir again to clear;
   * click the other dir to switch. Adjusts up/down counts accordingly. */
  vote(id: string, dir: 'up' | 'down'): Promise<Idea>;
  /** Re-rank ideas by the given id order (drag-to-reorder priority). */
  reorderPriority(orderedIds: string[]): Promise<Idea[]>;
  /** Suggested idea clusters (trigram + LLM grouping, degrades to ungrouped).
   * Optional productId scopes to one product. Suggestions only - never promotes. */
  suggestClusters(productId?: string): Promise<IdeaClusterSuggestions>;
  /** Hard-delete an idea. */
  remove(id: string): Promise<void>;
  /** Collapse `ideaIds` onto `survivorId` (issue #94, ideation round 2,
   * AC-94-01) - optional here so a caller typed only against the base
   * `IdeaService` (a test double, an older consumer) stays valid; every
   * concrete implementation (`IdeaExtendedOps`) always defines it. */
  merge?(survivorId: string, ideaIds: string[]): Promise<Idea>;
  /** Restore a merged child (or dissolve a survivor's whole group) - AC-94-07/08. */
  unmerge?(id: string): Promise<Idea[]>;
  /** The children merged into a survivor, oldest merge first (AC-94-03/25). */
  listMerged?(id: string): Promise<Idea[]>;
  /** The triage board - statuses grouped into columns with their cards
   * (AC-94-54/58), never a hardcoded FE column list. */
  getBoard?(opts?: { includeTest?: boolean; productId?: string }): Promise<Board>;
}

/** The merge/unmerge/board surface every concrete `IdeaService` always
 * implements (optional on the base interface so a partial test double still
 * satisfies it - see `use-idea-form.test.tsx`'s `fakeService`). */
export interface IdeaExtendedOps {
  merge(survivorId: string, ideaIds: string[]): Promise<Idea>;
  unmerge(id: string): Promise<Idea[]>;
  listMerged(id: string): Promise<Idea[]>;
  getBoard(opts?: { includeTest?: boolean; productId?: string }): Promise<Board>;
}

// Slice S5 (issue #94): bound to the real backend behind this ONE line - the
// mock (`./ideation-service.mock`) stays for the mock's own test suite and
// any test double that still wants it; no other file changes on this swap.
export const ideationService: IdeaService & IdeaExtendedOps = realIdeationService;
