'use client';

/**
 * Review-process admin Submissions overview (the staff god-view deferred in the
 * Cluster E AC §10). For ONE review configuration, lists EVERY submission group
 * with its current status, author, live average + a "ready" chip, and the
 * decision verdict. Expanding a row reveals the per-reviewer reviews (reviewer
 * name · status · score) — this is the ADMIN view, so it MAY surface raw
 * reviews/scores (unlike the author-visible My Submissions). Read-only.
 *
 * Reuses the shared primitives — EngineStatusBadge, ClampedText, Badge — never a
 * parallel component. Foolproof-UI: status/decision read straight off the engine;
 * the empty state is a status line, not how-to copy. Responsive: the rows wrap
 * and the nested reviews scroll on narrow screens.
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight, LoaderCircleIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { EngineStatusBadge } from '@/components/platform/review/engine-status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { cn } from '@/lib/utils';
import type {
  ReviewAdminReview,
  ReviewAdminReviewStatus,
  ReviewAdminSubmission,
  ReviewDecisionVerdict,
} from '@/types/review';

const DECISION_META: Record<
  ReviewDecisionVerdict,
  { label: string; tone: 'success' | 'destructive' | 'warning' }
> = {
  ACCEPTED: { label: 'Accepted', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'destructive' },
  REVISIONS: { label: 'Revisions requested', tone: 'warning' },
};

const REVIEW_STATUS_META: Record<
  ReviewAdminReviewStatus,
  { label: string; tone: 'success' | 'secondary' | 'warning' | 'destructive' }
> = {
  COMPLETED: { label: 'Completed', tone: 'success' },
  PENDING: { label: 'Pending', tone: 'secondary' },
  ESCALATED: { label: 'Escalated', tone: 'warning' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'destructive' },
};

function formatScore(score: number | null): string {
  if (score === null) return '—';
  return Number.isInteger(score) ? String(score) : score.toFixed(2);
}

export interface SubmissionsTabProps {
  submissions: ReviewAdminSubmission[];
  loading: boolean;
  error: string | null;
}

export function SubmissionsTab({ submissions, loading, error }: SubmissionsTabProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <LoaderCircleIcon className="size-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="py-12 text-center text-sm font-medium text-destructive">{error}</p>
    );
  }

  if (submissions.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="submissions-empty">
        No submissions yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" data-testid="admin-submissions-list">
      {submissions.map((s) => (
        <SubmissionRow key={s.groupId} submission={s} />
      ))}
    </ul>
  );
}

function SubmissionRow({ submission: s }: { submission: ReviewAdminSubmission }) {
  const { formatDateTime } = useDatetime();
  const [open, setOpen] = useState(false);
  const decisionMeta = s.decision ? DECISION_META[s.decision.decision] : null;
  const hasReviews = s.reviews.length > 0;

  return (
    <li
      data-testid="admin-submission-row"
      className="rounded-xl border border-border bg-card"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-start justify-between gap-3 p-4 text-left"
      >
        <div className="flex min-w-0 items-start gap-2">
          <span className="mt-0.5 text-muted-foreground">
            {open ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </span>
          <div className="min-w-0 space-y-1.5">
            <p className="truncate font-medium text-mono">{s.title}</p>
            <p className="truncate text-xs text-muted-foreground">
              {s.author ? s.author.name : 'Anonymous'} · Revision {s.revisionNumber}
              {s.submittedAt && <> · {formatDateTime(s.submittedAt)}</>}
            </p>
            {s.decision?.feedbackText && (
              <ClampedText
                text={s.decision.feedbackText}
                lines={2}
                className="rounded-md bg-muted/50 px-3 py-2 text-sm text-foreground"
              />
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <EngineStatusBadge
            statusKey={s.statusId}
            label={s.statusLabel}
            color={s.statusColor}
            size="sm"
          />
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge variant="secondary" appearance="light" size="sm" data-testid="avg-chip">
              Avg {formatScore(s.averageScore)}
            </Badge>
            <Badge
              variant={s.ready ? 'success' : 'secondary'}
              appearance="light"
              size="sm"
              data-testid="ready-chip"
            >
              {s.completedCount}/{s.requiredReviewCount} reviews
            </Badge>
            <Badge
              variant={decisionMeta ? decisionMeta.tone : 'outline'}
              appearance="light"
              size="sm"
              data-testid="decision-chip"
            >
              {decisionMeta ? decisionMeta.label : 'No decision'}
            </Badge>
          </div>
        </div>
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3" data-testid="admin-submission-detail">
          {hasReviews ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="pb-2 pr-4 font-medium">Reviewer</th>
                    <th className="pb-2 pr-4 font-medium">Status</th>
                    <th className="pb-2 font-medium">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {s.reviews.map((r) => (
                    <ReviewRow key={r.assignmentId} review={r} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-2 text-sm text-muted-foreground">No reviewers assigned yet.</p>
          )}

          {s.decision && (
            <div className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
              Decided by {s.decision.deciderName}
              {s.decision.decidedAt && <> · {formatDateTime(s.decision.decidedAt)}</>}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function ReviewRow({ review: r }: { review: ReviewAdminReview }) {
  const meta = REVIEW_STATUS_META[r.status];
  return (
    <tr className="border-t border-border/60" data-testid="admin-review-row">
      <td className={cn('py-2 pr-4', 'truncate')}>{r.reviewerName}</td>
      <td className="py-2 pr-4">
        <Badge variant={meta.tone} appearance="light" size="sm">
          {meta.label}
        </Badge>
      </td>
      <td className="py-2 font-medium text-mono">{formatScore(r.score)}</td>
    </tr>
  );
}
