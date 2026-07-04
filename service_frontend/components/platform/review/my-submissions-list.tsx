'use client';

/**
 * My Submissions list (plan sprint-4/06 slice 2, AC-06-43/08/52). The author's
 * own submissions with lifecycle status + decision + optional feedback — NEVER
 * raw reviews or scores. A Revise action shows only when `canRevise` (the
 * backend sets it when the group is at the revisions status + the window is
 * open). Portal-only surface (authors are Profiles), but identity-agnostic in
 * shape.
 *
 * Foolproof-UI: status/decision read straight off the engine; no how-to copy.
 */
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useDatetime } from '@/hooks/use-datetime';
import { EngineStatusBadge } from './engine-status-badge';
import type { MySubmission, ReviewDecision } from '@/types/portal-review';

const DECISION_META: Record<ReviewDecision, { label: string; tone: 'success' | 'destructive' | 'warning' }> = {
  ACCEPTED: { label: 'Accepted', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'destructive' },
  REVISIONS: { label: 'Revisions requested', tone: 'warning' },
};

export interface MySubmissionsListProps {
  submissions: MySubmission[];
  onRevise: (submission: MySubmission) => void;
  submissionNoun?: string;
  /** Show the per-row event/context label (AC-06-25) — true when the global
   * event filter is OFF so items across contexts carry their context per row. */
  showContext?: boolean;
}

export function MySubmissionsList({
  submissions,
  onRevise,
  submissionNoun = 'Submission',
  showContext = false,
}: MySubmissionsListProps) {
  const { formatDateTime } = useDatetime();

  if (submissions.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No {submissionNoun.toLowerCase()}s yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" data-testid="my-submissions-list">
      {submissions.map((s) => {
        const decisionMeta = s.decision ? DECISION_META[s.decision] : null;
        return (
          <li
            key={s.groupId}
            data-testid="my-submission-row"
            className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-card p-4"
          >
            <div className="min-w-0 space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <p className="truncate font-medium text-mono">{s.title}</p>
                {showContext && s.contextLabel && (
                  <Badge variant="secondary" appearance="light" size="sm" data-testid="row-context">
                    {s.contextLabel}
                  </Badge>
                )}
              </div>
              <p className="truncate text-xs text-muted-foreground">
                {s.reviewConfigurationName} · Revision {s.revisionNumber}
                {s.submittedAt && <> · {formatDateTime(s.submittedAt)}</>}
              </p>
              {s.feedbackText && (
                <p
                  data-testid="submission-feedback"
                  className="rounded-md bg-muted/50 px-3 py-2 text-sm text-foreground"
                >
                  {s.feedbackText}
                </p>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              <div className="flex flex-wrap items-center justify-end gap-2">
                <EngineStatusBadge
                  statusKey={s.statusId}
                  label={s.statusLabel}
                  color={s.statusColor}
                  size="sm"
                />
                {decisionMeta && (
                  <Badge variant={decisionMeta.tone} appearance="light" size="sm">
                    {decisionMeta.label}
                  </Badge>
                )}
              </div>
              {s.canRevise && (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="revise-button"
                  onClick={() => onRevise(s)}
                >
                  Revise
                </Button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
