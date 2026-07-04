/**
 * Review/Approval SURFACE wire types (plan sprint-4/06 slice 2) — the shapes the
 * My Submissions / My Reviews (two-pane) / Decisions surfaces consume. Mirrors
 * the backend camelCase contracts in `app/schemas/review.py` (MySubmissionOut,
 * MyReviewOut, ReviewTwoPaneOut, DecisionQueueItemOut, …).
 *
 * Identity-agnostic: NOTHING here says "profile" or "user" — the SAME shapes are
 * served to the staff `(protected)` surfaces (user-kind actors) and the portal
 * `(portal)` surfaces (profile-kind actors). The page supplies the right
 * service; the shared components branch on NOTHING (AC-06-46/47/54).
 */
import type { FormDocument, FormAnswers } from '@/types/forms';

/** Submission lifecycle status as resolved by the status engine (label + hex). */
export interface ReviewStatusRef {
  id: string;
  label: string;
  color: string;
}

/** Terminal decision an actor with `can_decide` may take (AC-06-07/45). */
export type ReviewDecision = 'ACCEPTED' | 'REJECTED' | 'REVISIONS';

/** One row in My Submissions (AC-06-43/08) — lifecycle + decision + optional
 * feedback ONLY. Raw reviews/scores are NEVER part of this shape. */
export interface MySubmission {
  groupId: string;
  submissionId: string;
  reviewConfigurationId: string;
  reviewConfigurationName: string;
  /** The config's bound event/context (AC-06-25) — null for a context-less
   * config; `contextLabel` is the real event name for per-row labelling. */
  contextId: string | null;
  contextLabel: string | null;
  formId: string;
  title: string;
  revisionNumber: number;
  statusId: string;
  statusLabel: string;
  statusColor: string;
  decision: ReviewDecision | null;
  feedbackText: string | null;
  decidedAt: string | null;
  canRevise: boolean;
  submittedAt: string | null;
  createdAt: string | null;
}

/** A review configuration the current actor may submit to (AC-06-03) — surfaced
 * even with ZERO prior submissions. `canSubmitNow` reflects the live window +
 * tier-1 block state; the backend is the real gate. */
export type SubmitWindowState = 'open' | 'closed' | 'notYetOpen';

export interface SubmitOption {
  configId: string;
  name: string;
  contextId: string | null;
  contextLabel: string | null;
  submissionFormId: string;
  windowState: SubmitWindowState;
  windowStart: string | null;
  windowEnd: string | null;
  canSubmitNow: boolean;
}

/** The author's view of a submission group's CURRENT revision INCLUDING answers
 * (AC-06-09) — used to prefill the revise form. Lifecycle + decision only; never
 * raw reviews/scores. */
export interface SubmissionDetail extends MySubmission {
  answers: FormAnswers;
  versionId: string;
}

/** Per-config submit entry point shown in My Submissions while a window is open.
 * Derived client-side from the surfaces (one entry per config the actor can
 * submit to); the backend gates the actual submit. */
export interface SubmitFormState {
  state: 'open' | 'closed' | 'blocked' | 'not_eligible';
  configId?: string;
  message?: string;
  form?: {
    formId: string;
    versionId: string;
    name: string;
    description: string | null;
    definition: FormDocument;
    paged: boolean;
  };
}

/** One assignment in the reviewer queue (AC-06-44). `dueAt` = the window end. */
export interface MyReview {
  assignmentId: string;
  reviewConfigurationId: string;
  reviewConfigurationName: string;
  contextId: string | null;
  contextLabel: string | null;
  groupId: string;
  revisionNumber: number;
  status: 'PENDING' | 'COMPLETED' | 'ESCALATED' | 'WITHDRAWN';
  dueAt: string | null;
  assignedAt: string | null;
  completedAt: string | null;
  title: string;
}

/** The read-only submission pane payload (pinned version + answers). */
export interface ReviewSubmissionPane {
  id: string;
  formId: string;
  versionId: string;
  answers: FormAnswers;
  definition: FormDocument | null;
  revisionNumber: number;
}

/** The review-form (rubric) fill pane payload. */
export interface ReviewFormPane {
  formId: string;
  versionId: string;
  versionNumber: number;
  name: string;
  description: string | null;
  definition: FormDocument;
  paged: boolean;
}

/** THIS reviewer's own in-progress draft (reviewer isolation — never another's). */
export interface ReviewDraftPane {
  submissionId: string;
  answers: FormAnswers;
  status?: string;
}

/** The full two-pane grade payload (AC-06-05/48). */
export interface ReviewTwoPane {
  assignmentId: string;
  status: 'PENDING' | 'COMPLETED' | 'ESCALATED' | 'WITHDRAWN';
  reviewConfigurationId: string;
  reviewConfigurationName: string;
  submission: ReviewSubmissionPane;
  reviewForm: ReviewFormPane | null;
  reviewDraft: ReviewDraftPane | null;
}

/** One completed review inside a decision group (decider-only — AC-06-07). */
export interface DecisionReview {
  assignmentId: string;
  reviewSubmissionId: string;
  answers: FormAnswers;
  score: number | null;
  completedAt: string | null;
}

/** One group in the Decisions surface (AC-06-45/07). */
export interface DecisionItem {
  groupId: string;
  submissionId: string;
  reviewConfigurationId: string;
  reviewConfigurationName: string;
  contextId: string | null;
  contextLabel: string | null;
  title: string;
  revisionNumber: number;
  statusId: string;
  statusLabel: string;
  statusColor: string;
  averageScore: number | null;
  completedCount: number;
  requiredReviewCount: number;
  ready: boolean;
  decision: ReviewDecision | null;
  feedbackText: string | null;
  reviews: DecisionReview[];
  submittedAt: string | null;
  createdAt: string | null;
}

/** Save-draft / submit result for a review (assignment). */
export interface ReviewDraftResult {
  submissionId: string;
  answers: FormAnswers;
}

/** Revise result (a fresh Draft revision to fill). */
export interface ReviseResult {
  submissionId: string;
  groupId: string;
  revisionNumber: number;
}

/**
 * The data + actions a surface page passes into a shared presentational
 * component (the two-pane grade view, the decision panel). Identity-agnostic:
 * the page supplies the right service-bound callbacks; the component never knows
 * whether it is staff or portal (AC-06-46/47, reuse-don't-rebuild).
 */
export interface ReviewSurfaceActions {
  /** Resolve the two-pane payload for an assignment. */
  getTwoPane(assignmentId: string): Promise<ReviewTwoPane>;
  /** Save the review draft (resume later). */
  saveDraft(assignmentId: string, answers: FormAnswers): Promise<ReviewDraftResult>;
  /** Submit the review (terminal — assignment → COMPLETED). */
  submitReview(assignmentId: string, answers: FormAnswers): Promise<unknown>;
}

export interface DecisionSurfaceActions {
  /** Take the terminal decision for a group (first-wins; 409 if already decided). */
  decide(
    groupId: string,
    decision: ReviewDecision,
    feedback: string | null,
  ): Promise<DecisionItem>;
}
