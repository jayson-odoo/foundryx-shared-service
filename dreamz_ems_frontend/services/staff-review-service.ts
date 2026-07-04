/**
 * Staff review-surface service boundary (plan sprint-4/06 slice 2, AC-06-46).
 * The staff `(protected)` My Reviews + Decisions surfaces reach data ONLY
 * through this interface (UI → hook → service → api-client). Staff-session
 * bound (the SAME shapes as the portal service, but the staff JWT + perms).
 *
 * Reuses the shared `review-surface-normalize` helpers so the staff two-pane and
 * the portal two-pane feed the SAME shared components from one camelCase shape.
 */
import type { FormAnswers } from '@/types/forms';
import type {
  DecisionItem,
  MyReview,
  ReviewDecision,
  ReviewDraftResult,
  ReviewTwoPane,
} from '@/types/portal-review';
import { realStaffReviewService } from './staff-review-service.real';

export interface StaffReviewService {
  myReviews(): Promise<MyReview[]>;
  reviewTwoPane(assignmentId: string): Promise<ReviewTwoPane>;
  saveReviewDraft(assignmentId: string, answers: FormAnswers): Promise<ReviewDraftResult>;
  submitReview(assignmentId: string, answers: FormAnswers): Promise<unknown>;
  decisions(): Promise<DecisionItem[]>;
  decide(
    groupId: string,
    decision: ReviewDecision,
    feedback: string | null,
  ): Promise<DecisionItem>;
}

export const staffReviewService: StaffReviewService = realStaffReviewService;
