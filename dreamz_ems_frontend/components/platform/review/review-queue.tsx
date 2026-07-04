'use client';

/**
 * Shared My Reviews QUEUE (plan sprint-4/06 slice 2, AC-06-44). One list of the
 * actor's assignments (PENDING/COMPLETED, due = window end). Identity-agnostic —
 * staff + portal both render it; the page supplies `onOpen` (route to its own
 * two-pane page). Reviewer isolation is a backend guarantee (the queue only ever
 * contains THIS actor's assignments).
 */
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useDatetime } from '@/hooks/use-datetime';
import type { MyReview } from '@/types/portal-review';

export interface ReviewQueueProps {
  reviews: MyReview[];
  onOpen: (assignmentId: string) => void;
  reviewNoun?: string;
  /** Show the per-row event/context label (AC-06-25) — true when the global
   * event filter is OFF. */
  showContext?: boolean;
}

const STATUS_TONE: Record<MyReview['status'], 'warning' | 'success' | 'destructive' | 'secondary'> = {
  PENDING: 'warning',
  COMPLETED: 'success',
  ESCALATED: 'destructive',
  WITHDRAWN: 'secondary',
};

export function ReviewQueue({
  reviews,
  onOpen,
  reviewNoun = 'Review',
  showContext = false,
}: ReviewQueueProps) {
  const { formatDateTime } = useDatetime();

  if (reviews.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        No {reviewNoun.toLowerCase()}s assigned.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" data-testid="review-queue">
      {reviews.map((r) => (
        <li
          key={r.assignmentId}
          data-testid="review-queue-item"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4"
        >
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate font-medium text-mono">{r.title}</p>
              {showContext && r.contextLabel && (
                <Badge variant="secondary" appearance="light" size="sm" data-testid="row-context">
                  {r.contextLabel}
                </Badge>
              )}
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {r.reviewConfigurationName} · Revision {r.revisionNumber}
              {r.dueAt && <> · Due {formatDateTime(r.dueAt)}</>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={STATUS_TONE[r.status]} appearance="light" size="sm">
              {r.status === 'PENDING'
                ? 'To do'
                : r.status === 'COMPLETED'
                  ? 'Done'
                  : r.status === 'ESCALATED'
                    ? 'Escalated'
                    : 'Withdrawn'}
            </Badge>
            <Button size="sm" variant="outline" onClick={() => onOpen(r.assignmentId)}>
              {r.status === 'COMPLETED' ? 'View' : 'Open'}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
