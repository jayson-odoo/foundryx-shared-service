'use client';

import { ArrowRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import { isBlanking, type AutocountPreviewFieldDiff } from '@/types/autocount';
import { DiffValue } from './record-diff';

/** Shared grid - mirrors `RecordDiff` so a dry-run diff reads the same way. */
const ROW_GRID =
  'grid grid-cols-1 gap-x-3 gap-y-1 md:grid-cols-[minmax(140px,220px)_1fr_auto_1fr] md:items-start';

export interface PredictionDiffProps {
  /** `column → {current, incoming}` - Sorento's own dry-run resolution. */
  diff: Record<string, AutocountPreviewFieldDiff>;
  className?: string;
}

/**
 * A prediction's field-level current → incoming (AC-14-20/22). A BLANKING
 * (a live value replaced by nothing) is the destructive case - its row is
 * tinted with the destructive token and tagged, legible from styling alone
 * (foolproof-UI: no explanatory paragraph). Theme-aware light and dark.
 *
 * Stacks on mobile (label / current / incoming each on their own line), lays
 * out in columns from `md` up - no horizontal page scroll at 375px.
 */
export function PredictionDiff({ diff, className }: PredictionDiffProps) {
  const fields = Object.keys(diff).sort((a, b) => a.localeCompare(b));

  if (fields.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="prediction-no-changes">
        No field changes.
      </p>
    );
  }

  return (
    <div className={cn('flex flex-col gap-2', className)} data-testid="prediction-diff">
      <div
        className={cn(ROW_GRID, 'hidden md:grid text-xs font-medium text-muted-foreground')}
      >
        <span>Field</span>
        <span>Current</span>
        <span aria-hidden="true" />
        <span>Incoming</span>
      </div>

      {fields.map((field) => {
        const change = diff[field];
        const blanking = isBlanking(change);
        return (
          <div
            key={field}
            data-testid={`prediction-row-${field}`}
            data-blanking={blanking ? 'true' : undefined}
            className={cn(
              ROW_GRID,
              'rounded-md border border-transparent border-t-border pt-3 md:pt-2',
              blanking &&
                'border-destructive/40 bg-destructive/5 px-2 py-2 md:px-3 dark:bg-destructive/10',
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {humanizeFieldKey(field)}
              </span>
              {blanking && (
                <Badge variant="destructive" appearance="light" size="sm">
                  Cleared
                </Badge>
              )}
            </div>

            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-xs text-muted-foreground md:hidden">Current</span>
              <DiffValue value={change.current} tone="before" />
            </div>

            <ArrowRight
              className={cn(
                'hidden size-4 shrink-0 self-center md:block',
                blanking ? 'text-destructive' : 'text-muted-foreground',
              )}
              aria-hidden="true"
            />

            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-xs text-muted-foreground md:hidden">Incoming</span>
              <DiffValue value={change.incoming} tone="after" />
            </div>
          </div>
        );
      })}
    </div>
  );
}
