/**
 * Real portal review-surface service (plan sprint-4/06 slice 2). Hits the
 * Profile-authed `/portal/*` review endpoints via the PORTAL api-client (never
 * the staff session).
 *
 * NORMALIZATION NOTE: the two-pane `submission`/`reviewForm`/`reviewDraft` and
 * the `submit-form` `form` payloads are raw dicts on the backend (FastAPI does
 * not recurse-serialize a `Dict[str, Any]` field), so their inner keys arrive
 * snake_case. We normalize them to the camelCase pane shapes here so the shared
 * components stay clean.
 */
import { portalApiFetch } from '@/lib/portal-api-client';
import type { FormAnswers } from '@/types/forms';
import type {
  DecisionItem,
  MyReview,
  MySubmission,
  ReviewDraftResult,
  ReviewTwoPane,
  ReviseResult,
  SubmissionDetail,
  SubmitFormState,
  SubmitOption,
  SubmitWindowState,
} from '@/types/portal-review';
import type { PortalReviewService } from './portal-review-service';
import {
  normalizeFormPane,
  normalizeMySubmission,
  normalizeTwoPane,
} from './review-surface-normalize';

/** Backend snake window state → camel union. */
function windowState(raw: unknown): SubmitWindowState {
  if (raw === 'closed') return 'closed';
  if (raw === 'not_yet_open') return 'notYetOpen';
  return 'open';
}

/** Append the active event/context filter (AC-06-25) when one is set. */
function withContext(path: string, contextId?: string | null): string {
  if (!contextId) return path;
  return `${path}?contextId=${encodeURIComponent(contextId)}`;
}

export const realPortalReviewService: PortalReviewService = {
  // ---- My Submissions ----
  mySubmissions(token, contextId) {
    return portalApiFetch<MySubmission[]>(
      withContext('/portal/submissions', contextId),
      { token },
    );
  },

  async submitOptions(token, contextId): Promise<SubmitOption[]> {
    const rows = await portalApiFetch<Record<string, unknown>[]>(
      withContext('/portal/submit-options', contextId),
      { token },
    );
    return rows.map((r) => ({
      configId: String(r.config_id),
      name: String(r.name ?? ''),
      contextId: r.context_id ? String(r.context_id) : null,
      contextLabel: r.context_label ? String(r.context_label) : null,
      submissionFormId: String(r.submission_form_id ?? ''),
      windowState: windowState(r.window_state),
      windowStart: r.window_start ? String(r.window_start) : null,
      windowEnd: r.window_end ? String(r.window_end) : null,
      canSubmitNow: Boolean(r.can_submit_now),
    }));
  },

  async submissionDetail(groupId, token): Promise<SubmissionDetail> {
    const raw = await portalApiFetch<Record<string, unknown>>(
      `/portal/submissions/${groupId}`,
      { token },
    );
    return {
      ...normalizeMySubmission(raw),
      answers: (raw.answers as SubmissionDetail['answers']) ?? {},
      versionId: String(raw.version_id ?? ''),
    };
  },

  async submitFormView(configId, token): Promise<SubmitFormState> {
    const raw = await portalApiFetch<Record<string, unknown>>(
      `/portal/review-configs/${configId}/submit-form`,
      { token },
    );
    const state = String(raw.state) as SubmitFormState['state'];
    if (state !== 'open') {
      return { state, message: raw.message ? String(raw.message) : undefined };
    }
    return {
      state: 'open',
      configId: raw.config_id ? String(raw.config_id) : configId,
      form: normalizeFormPane(raw.form as Record<string, unknown>) as SubmitFormState['form'],
    };
  },

  submit(configId, answers, token) {
    return portalApiFetch<MySubmission>(
      `/portal/review-configs/${configId}/submissions`,
      { method: 'POST', body: JSON.stringify({ answers }), token },
    );
  },

  async revise(groupId, token): Promise<ReviseResult> {
    const raw = await portalApiFetch<Record<string, unknown>>(
      `/portal/submissions/${groupId}/revise`,
      { method: 'POST', token },
    );
    return {
      submissionId: String(raw.submission_id),
      groupId: String(raw.group_id),
      revisionNumber: Number(raw.revision_number),
    };
  },

  resubmit(submissionId, answers, token) {
    return portalApiFetch<MySubmission>(
      `/portal/submissions/${submissionId}/resubmit`,
      { method: 'POST', body: JSON.stringify({ answers }), token },
    );
  },

  // ---- My Reviews ----
  myReviews(token, contextId) {
    return portalApiFetch<MyReview[]>(withContext('/portal/reviews', contextId), {
      token,
    });
  },

  async reviewTwoPane(assignmentId, token): Promise<ReviewTwoPane> {
    const raw = await portalApiFetch<Record<string, unknown>>(
      `/portal/reviews/${assignmentId}`,
      { token },
    );
    return normalizeTwoPane(raw);
  },

  async saveReviewDraft(assignmentId, answers, token): Promise<ReviewDraftResult> {
    const raw = await portalApiFetch<Record<string, unknown>>(
      `/portal/reviews/${assignmentId}/draft`,
      { method: 'POST', body: JSON.stringify({ answers }), token },
    );
    return {
      submissionId: String(raw.submission_id),
      answers: (raw.answers as FormAnswers) ?? {},
    };
  },

  submitReview(assignmentId, answers, token) {
    return portalApiFetch<unknown>(`/portal/reviews/${assignmentId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
      token,
    });
  },

  // ---- Decisions ----
  decisions(token, contextId) {
    return portalApiFetch<DecisionItem[]>(
      withContext('/portal/decisions', contextId),
      { token },
    );
  },

  decide(groupId, decision, feedback, token) {
    return portalApiFetch<DecisionItem>(`/portal/decisions/${groupId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, feedback }),
      token,
    });
  },
};
