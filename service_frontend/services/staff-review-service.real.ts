/**
 * Real staff review-surface service (plan sprint-4/06 slice 2). Hits the
 * staff-authed `/reviews/*` surface endpoints via the shared api-client (gated
 * `reviews.grade` / `reviews.decide`). Normalizes the raw pane dicts to the
 * camelCase shared shape via `review-surface-normalize`.
 */
import { apiFetch } from '@/lib/api-client';
import type { FormAnswers } from '@/types/forms';
import type {
  DecisionItem,
  MyReview,
  ReviewDraftResult,
  ReviewTwoPane,
} from '@/types/portal-review';
import type { StaffReviewService } from './staff-review-service';
import { normalizeTwoPane } from './review-surface-normalize';

export const realStaffReviewService: StaffReviewService = {
  myReviews() {
    return apiFetch<MyReview[]>('/reviews/my-reviews');
  },

  async reviewTwoPane(assignmentId): Promise<ReviewTwoPane> {
    const raw = await apiFetch<Record<string, unknown>>(
      `/reviews/assignments/${assignmentId}`,
    );
    return normalizeTwoPane(raw);
  },

  async saveReviewDraft(assignmentId, answers): Promise<ReviewDraftResult> {
    const raw = await apiFetch<Record<string, unknown>>(
      `/reviews/assignments/${assignmentId}/draft`,
      { method: 'POST', body: JSON.stringify({ answers }) },
    );
    return {
      submissionId: String(raw.submission_id),
      answers: (raw.answers as FormAnswers) ?? {},
    };
  },

  submitReview(assignmentId, answers) {
    return apiFetch<unknown>(`/reviews/assignments/${assignmentId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    });
  },

  decisions() {
    return apiFetch<DecisionItem[]>('/reviews/decisions');
  },

  decide(groupId, decision, feedback) {
    return apiFetch<DecisionItem>(`/reviews/decisions/${groupId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, feedback }),
    });
  },
};
