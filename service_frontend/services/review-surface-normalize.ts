/**
 * Shared snake_case → camelCase normalizers for the review SURFACE panes (plan
 * sprint-4/06 slice 2). The two-pane `submission`/`reviewForm`/`reviewDraft` and
 * the `submit-form` `form` payloads are raw `Dict[str, Any]` on the backend, so
 * FastAPI leaves their inner keys snake_case. BOTH the portal and the staff real
 * services normalize through here so the shared components consume one clean
 * camelCase shape.
 */
import type { FormAnswers, FormDocument } from '@/types/forms';
import type {
  MySubmission,
  ReviewDecision,
  ReviewDraftPane,
  ReviewFormPane,
  ReviewSubmissionPane,
  ReviewTwoPane,
} from '@/types/portal-review';

/** Normalize the author-visible group raw dict (snake keys from
 * `author_visible_group`) into the camelCase `MySubmission` shape — used by the
 * submission-detail endpoint (which returns a raw `Dict[str, Any]`). */
export function normalizeMySubmission(raw: Record<string, unknown>): MySubmission {
  return {
    groupId: String(raw.group_id),
    submissionId: String(raw.submission_id),
    reviewConfigurationId: String(raw.review_configuration_id ?? ''),
    reviewConfigurationName: String(raw.review_configuration_name ?? ''),
    contextId: raw.context_id ? String(raw.context_id) : null,
    contextLabel: raw.context_label ? String(raw.context_label) : null,
    formId: String(raw.form_id ?? ''),
    title: String(raw.title ?? ''),
    revisionNumber: Number(raw.revision_number ?? 1),
    statusId: String(raw.status_id ?? ''),
    statusLabel: String(raw.status_label ?? ''),
    statusColor: String(raw.status_color ?? 'gray'),
    decision: (raw.decision as ReviewDecision | null) ?? null,
    feedbackText: (raw.feedback_text as string | null) ?? null,
    decidedAt: (raw.decided_at as string | null) ?? null,
    canRevise: Boolean(raw.can_revise),
    submittedAt: (raw.submitted_at as string | null) ?? null,
    createdAt: (raw.created_at as string | null) ?? null,
  };
}

export function normalizeSubmissionPane(
  raw: Record<string, unknown>,
): ReviewSubmissionPane {
  return {
    id: String(raw.id),
    formId: String(raw.form_id),
    versionId: String(raw.version_id ?? ''),
    answers: (raw.answers as FormAnswers) ?? {},
    definition: (raw.definition as FormDocument | null) ?? null,
    revisionNumber: Number(raw.revision_number ?? 1),
  };
}

export function normalizeFormPane(
  raw: Record<string, unknown> | null | undefined,
): ReviewFormPane | null {
  if (!raw) return null;
  return {
    formId: String(raw.form_id),
    versionId: String(raw.version_id ?? ''),
    versionNumber: Number(raw.version_number ?? 0),
    name: String(raw.name ?? ''),
    description: (raw.description as string | null) ?? null,
    definition: (raw.definition as FormDocument) ?? { schemaVersion: 1, pages: [] },
    paged: Boolean(raw.paged),
  };
}

function normalizeDraftPane(
  raw: Record<string, unknown> | null | undefined,
): ReviewDraftPane | null {
  if (!raw) return null;
  return {
    submissionId: String(raw.submission_id),
    answers: (raw.answers as FormAnswers) ?? {},
    status: raw.status ? String(raw.status) : undefined,
  };
}

/** Normalize the full two-pane payload — the top-level keys are already
 * camelCase (aliased by `ReviewTwoPaneOut`); only the nested dicts need it. */
export function normalizeTwoPane(raw: Record<string, unknown>): ReviewTwoPane {
  return {
    assignmentId: String(raw.assignmentId),
    status: raw.status as ReviewTwoPane['status'],
    reviewConfigurationId: String(raw.reviewConfigurationId),
    reviewConfigurationName: String(raw.reviewConfigurationName ?? ''),
    submission: normalizeSubmissionPane(raw.submission as Record<string, unknown>),
    reviewForm: normalizeFormPane(raw.reviewForm as Record<string, unknown> | null),
    reviewDraft: normalizeDraftPane(raw.reviewDraft as Record<string, unknown> | null),
  };
}
