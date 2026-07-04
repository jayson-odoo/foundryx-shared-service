/**
 * Portal review-surface service boundary (plan sprint-4/06 slice 2). The Profile
 * portal My Submissions / My Reviews / Decisions surfaces reach data ONLY
 * through this interface (portal UI → hook → service → portal-api-client →
 * FastAPI). Profile-session bound — NEVER the staff session.
 *
 * Phase B binds the real portal-api-client; the mock stays for Vitest. The swap
 * is the one line at the bottom.
 */
import type { FormAnswers } from '@/types/forms';
import type {
  DecisionItem,
  MyReview,
  MySubmission,
  ReviewDecision,
  ReviewDraftResult,
  ReviewTwoPane,
  ReviseResult,
  SubmissionDetail,
  SubmitFormState,
  SubmitOption,
} from '@/types/portal-review';
import { realPortalReviewService } from './portal-review-service.real';

export interface PortalReviewService {
  // My Submissions
  /** ``contextId`` narrows to one event (AC-06-25); omit/null = all contexts. */
  mySubmissions(token?: string | null, contextId?: string | null): Promise<MySubmission[]>;
  /** Configs the current actor may submit to (AC-06-03) — independent of any
   * existing submissions. ``contextId`` narrows to one event (AC-06-25). */
  submitOptions(token?: string | null, contextId?: string | null): Promise<SubmitOption[]>;
  /** The author's own submission group + current-revision answers (AC-06-09). */
  submissionDetail(groupId: string, token?: string | null): Promise<SubmissionDetail>;
  submitFormView(configId: string, token?: string | null): Promise<SubmitFormState>;
  submit(
    configId: string,
    answers: FormAnswers,
    token?: string | null,
  ): Promise<MySubmission>;
  revise(groupId: string, token?: string | null): Promise<ReviseResult>;
  resubmit(
    submissionId: string,
    answers: FormAnswers,
    token?: string | null,
  ): Promise<MySubmission>;

  // My Reviews (two-pane)
  /** ``contextId`` narrows to one event (AC-06-25); omit/null = all contexts. */
  myReviews(token?: string | null, contextId?: string | null): Promise<MyReview[]>;
  reviewTwoPane(assignmentId: string, token?: string | null): Promise<ReviewTwoPane>;
  saveReviewDraft(
    assignmentId: string,
    answers: FormAnswers,
    token?: string | null,
  ): Promise<ReviewDraftResult>;
  submitReview(
    assignmentId: string,
    answers: FormAnswers,
    token?: string | null,
  ): Promise<unknown>;

  // Decisions
  /** ``contextId`` narrows to one event (AC-06-25); omit/null = all contexts. */
  decisions(token?: string | null, contextId?: string | null): Promise<DecisionItem[]>;
  decide(
    groupId: string,
    decision: ReviewDecision,
    feedback: string | null,
    token?: string | null,
  ): Promise<DecisionItem>;
}

export const portalReviewService: PortalReviewService = realPortalReviewService;
