/**
 * Ideation service — the boundary the UI talks to (plan: documentation/plans/
 * ideation/, Phase A). The interface IS the backend contract (§5.1: the
 * `create_idea` HTTP endpoint + idea reads). Phase-1 binds the in-memory MOCK
 * (swap is the ONE line at the bottom); Phase-2 will add `ideation-service.real.ts`
 * (apiFetch against shared-service) and bind it here.
 *
 * Enforced layering: UI → hooks → this service → lib/api-client → FastAPI.
 */
import type { Idea, IdeaStatus, Product } from '@/types/ideation';
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
  /** All ideas, newest first. */
  listIdeas(): Promise<Idea[]>;
  /** One idea by id (form view). Rejects if not found. */
  getIdea(id: string): Promise<Idea>;
  /** Update editable idea fields (form view save). */
  updateIdea(id: string, input: Partial<IdeaCreateInput> & { status?: IdeaStatus }): Promise<Idea>;
  /** Manually create a captured idea (deterministic — no LLM at shared-service). */
  createIdea(input: IdeaCreateInput): Promise<Idea>;
  /** Move an idea to a new lifecycle status (triage board drag / row action). */
  setStatus(id: string, status: IdeaStatus): Promise<Idea>;
  /** Toggle the current user's vote (one per user): click same dir again to clear;
   * click the other dir to switch. Adjusts up/down counts accordingly. */
  vote(id: string, dir: 'up' | 'down'): Promise<Idea>;
  /** Re-rank ideas by the given id order (drag-to-reorder priority). */
  reorderPriority(orderedIds: string[]): Promise<Idea[]>;
  /** Hard-delete an idea. */
  remove(id: string): Promise<void>;
}

// Phase 2: real api-client implementation. (Mock retained in *.mock.ts for tests.)
export const ideationService: IdeaService = realIdeationService;
