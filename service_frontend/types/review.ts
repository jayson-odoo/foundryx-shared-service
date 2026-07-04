/**
 * Review/Approval engine types (plan sprint-4/06, Cluster E slice 1). Mirrors
 * the backend camelCase wire contracts (app/schemas/review.py). The generic
 * "Review process" admin operates over ANY form_submission — nothing here is
 * EMS-specific (PERSONA/profile sources only render when the ems module is
 * active, but the shape stays identity-agnostic).
 */
import type { RuleFact, RuleGroup } from '@/types/rules';

/** Where a role's actors come from (AC-06-30). */
export type ReviewActorSource = 'RULE' | 'EXPLICIT' | 'PERSONA' | 'STAFF_ROLE';

/** A role is single identity-kind (AC-06-29) — never mixes users and profiles. */
export type ReviewActorIdentityKind = 'user' | 'profile';

/** One named actor of a role's identity kind (EXPLICIT/RULE candidate pool). */
export interface ReviewRoleActor {
  id: string;
  actorKind: ReviewActorIdentityKind;
  actorId: string;
  conditionsJson: RuleGroup | null;
  sortOrder: number;
}

/** Create/update shape for a role actor (no server id yet). */
export interface ReviewRoleActorInput {
  actorKind: ReviewActorIdentityKind;
  actorId: string;
  conditionsJson?: RuleGroup | null;
  sortOrder?: number;
}

/** A free-form per-config review role — capabilities drive behavior, the label
 * is display-only and inline-relabelable (AC-06-28/54). */
export interface ReviewRole {
  id: string;
  reviewConfigurationId: string;
  key: string;
  label: string;
  canSubmit: boolean;
  canReview: boolean;
  canDecide: boolean;
  actorSource: ReviewActorSource;
  actorIdentityKind: ReviewActorIdentityKind;
  boundPersonaId: string | null;
  boundStaffRoleId: string | null;
  conditionsJson: RuleGroup | null;
  sortOrder: number;
  actors: ReviewRoleActor[];
}

/** Create/update shape for a role (id assigned server-side on create). */
export interface ReviewRoleInput {
  key: string;
  label: string;
  canSubmit: boolean;
  canReview: boolean;
  canDecide: boolean;
  actorSource: ReviewActorSource;
  actorIdentityKind: ReviewActorIdentityKind;
  boundPersonaId?: string | null;
  boundStaffRoleId?: string | null;
  conditionsJson?: RuleGroup | null;
  sortOrder?: number;
  actors?: ReviewRoleActorInput[];
}

/** A review configuration over a (submission form, review/rubric form) pair. */
export interface ReviewConfig {
  id: string;
  name: string;
  formId: string;
  reviewFormId: string;
  requiredReviewCount: number;
  scoreFieldKey: string | null;
  windowStart: string | null;
  windowEnd: string | null;
  reviewStartStatusId: string | null;
  revisionsStatusId: string | null;
  acceptedStatusId: string | null;
  rejectedStatusId: string | null;
  isActive: boolean;
  roles: ReviewRole[];
  createdAt: string;
  updatedAt: string;
}

/** Create payload (name + the two forms are required server-side). */
export interface ReviewConfigCreateInput {
  name: string;
  formId: string;
  reviewFormId: string;
  requiredReviewCount?: number;
  scoreFieldKey?: string | null;
  windowStart?: string | null;
  windowEnd?: string | null;
  reviewStartStatusId?: string | null;
  revisionsStatusId?: string | null;
  acceptedStatusId?: string | null;
  rejectedStatusId?: string | null;
  isActive?: boolean;
  roles?: ReviewRoleInput[];
}

/** PATCH payload — every field optional; `roles` (when present) replaces the set. */
export type ReviewConfigUpdateInput = Partial<ReviewConfigCreateInput>;

export interface ReviewConfigListResult {
  data: ReviewConfig[];
  total: number;
}

// ---- admin Submissions overview (the staff god-view — AC §10 deferred) ----

/** A review decision verdict. */
export type ReviewDecisionVerdict = 'ACCEPTED' | 'REJECTED' | 'REVISIONS';

/** A review assignment's lifecycle on the admin overview. */
export type ReviewAdminReviewStatus =
  | 'PENDING'
  | 'COMPLETED'
  | 'ESCALATED'
  | 'WITHDRAWN';

/** The author of a submission group (identity-agnostic actor ref + display name). */
export interface ReviewAdminAuthor {
  kind: ReviewActorIdentityKind;
  id: string;
  name: string;
}

/** One reviewer's review on the admin overview — MAY carry the raw score (staff
 * view, unlike the author-visible surface). */
export interface ReviewAdminReview {
  assignmentId: string;
  reviewerKind: ReviewActorIdentityKind;
  reviewerId: string;
  reviewerName: string;
  status: ReviewAdminReviewStatus;
  score: number | null;
}

/** The terminal decision block (+ feedback, decider, decided-at). */
export interface ReviewAdminDecision {
  decision: ReviewDecisionVerdict;
  feedbackText: string | null;
  deciderKind: ReviewActorIdentityKind;
  deciderId: string;
  deciderName: string;
  decidedAt: string | null;
}

/** One submission group on the admin Submissions overview. */
export interface ReviewAdminSubmission {
  groupId: string;
  submissionId: string;
  revisionNumber: number;
  title: string;
  statusId: string;
  statusLabel: string;
  statusColor: string | null;
  author: ReviewAdminAuthor | null;
  submittedAt: string | null;
  createdAt: string | null;
  reviews: ReviewAdminReview[];
  averageScore: number | null;
  requiredReviewCount: number;
  completedCount: number;
  ready: boolean;
  decision: ReviewAdminDecision | null;
}

// ---- editor metadata (the only-valid-option pickers — AC-06-55) ----

/** One scoped status of the submission form (status-mapping select option). */
export interface ReviewMetaStatus {
  id: string;
  label: string;
  color: string;
}

/** One numeric field of the review form's published version (scoreFieldKey). */
export interface ReviewMetaField {
  key: string;
  label: string;
}

/** Picker universes for one (submission form, review form) pair. */
export interface ReviewConfigMeta {
  /** Submission form's scoped statuses — the ONLY valid status-mapping targets. */
  submissionStatuses: ReviewMetaStatus[];
  /** Review form's numeric fields — the ONLY valid scoreFieldKey options. */
  numericFields: ReviewMetaField[];
  /** Submission form answer facts for the RULE-role condition builder. */
  submissionFacts: RuleFact[];
}
