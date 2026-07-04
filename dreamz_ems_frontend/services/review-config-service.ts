/**
 * Review-config service boundary (plan sprint-4/06, Cluster E slice 1). The
 * standalone "Review processes" admin reaches data ONLY through this interface
 * (UI → hook → service → api-client). Phase B binds the real api-client; the
 * mock stays for offline UI iteration + Vitest. Swap is this one line.
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  ReviewAdminSubmission,
  ReviewConfig,
  ReviewConfigCreateInput,
  ReviewConfigMeta,
  ReviewConfigUpdateInput,
} from '@/types/review';
import { realReviewConfigService } from './review-config-service.real';

export interface ReviewConfigService {
  list(query: ListQuery): Promise<ListResult<ReviewConfig>>;
  get(id: string): Promise<ReviewConfig | null>;
  create(payload: ReviewConfigCreateInput): Promise<ReviewConfig>;
  update(id: string, payload: ReviewConfigUpdateInput): Promise<ReviewConfig>;
  remove(id: string): Promise<void>;
  /** Only-valid-option universes for the pickers (AC-06-55): submission-form
   * scoped statuses, review-form numeric fields, submission-form answer facts.
   * Pass the currently-selected form ids; either may be omitted. */
  meta(
    submissionFormId: string | null,
    reviewFormId: string | null,
  ): Promise<ReviewConfigMeta>;
  /** The admin Submissions overview (read-only staff god-view): every submission
   * group for the config → its reviews/scores → live average → decision. */
  adminSubmissions(configId: string): Promise<ReviewAdminSubmission[]>;
}

// Phase B: real api-client implementation (one-line boundary).
export const reviewConfigService: ReviewConfigService = realReviewConfigService;
