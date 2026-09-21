'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * `stage` -> the AC-11-27 label vocabulary (`Reading source` /
 * `Reading lookup <alias>` / `Combining` / `Mapping` /
 * `Checking with the consumer` / `Storing`). Any other value is rendered as
 * given rather than dropped, so a future stage never reads blank.
 */
function stageLabel(stage: string): string {
  if (stage === 'source') return 'Reading source';
  if (stage.startsWith('lookup:')) return `Reading lookup ${stage.slice('lookup:'.length)}`;
  if (stage === 'combine') return 'Combining';
  if (stage === 'mapping') return 'Mapping';
  if (stage === 'dry_run') return 'Checking with the consumer';
  if (stage === 'storing') return 'Storing';
  return stage;
}

export interface JobProgressProps {
  /** A non-terminal status this strip renders for; anything else renders
   * nothing (the caller owns terminal presentation - done/failed/cancelled
   * each have their own surface already). */
  status: 'queued' | 'running' | 'cancelling' | string;
  stage: string | null;
  /** Both null together = "not known yet" - never a fabricated percentage. */
  pagesDone: number | null;
  pagesTotal: number | null;
  /** Omitted = no Cancel control (a pull-snapshot build, BL-SS-248 - no
   * operator Cancel in this plan). */
  onCancel?: () => void;
  /** The Cancel button's accessible name - defaults to a generic one so
   * every call site is labelled without repeating itself. */
  cancelLabel?: string;
}

/**
 * The ONE running-state presentation (sprint-5/11, AC-11-27/43) reused by
 * the Source tab's Test, Review & Activate's Run preview, and the pull
 * snapshot detail's building hint - extended with a prop (`onCancel`),
 * never cloned (D5/AC-11-73).
 */
export function JobProgress({
  status,
  stage,
  pagesDone,
  pagesTotal,
  onCancel,
  cancelLabel = 'Cancel preview',
}: JobProgressProps) {
  if (status !== 'queued' && status !== 'running' && status !== 'cancelling') return null;

  const label = status === 'cancelling' ? 'Cancelling…' : stage ? stageLabel(stage) : 'Queued…';
  const showPages =
    status !== 'cancelling' && pagesDone !== null && pagesTotal !== null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 py-2 text-sm text-muted-foreground"
      data-testid="job-progress"
    >
      <LoaderCircleIcon className="size-4 animate-spin" aria-hidden />
      <span data-testid="job-progress-label">
        {label}
        {showPages && ` · page ${pagesDone} of ${pagesTotal}`}
      </span>
      {onCancel && status !== 'cancelling' && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          aria-label={cancelLabel}
          data-testid="job-progress-cancel"
        >
          Cancel
        </Button>
      )}
    </div>
  );
}
