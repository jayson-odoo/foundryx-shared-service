'use client';

import { ArrowRight } from 'lucide-react';
import { ClampedText } from '@/components/platform/clamped-text';
import { cn } from '@/lib/utils';
import {
  diffForDisplay,
  formatDiffValue,
  humanizeFieldKey,
  type DiffValueDisplay,
} from '@/lib/autocount-diff';

/** Grid template shared by the header and every change row. */
const ROW_GRID =
  'grid grid-cols-1 gap-x-3 gap-y-1 md:grid-cols-[minmax(140px,220px)_1fr_auto_1fr] md:items-start';

export interface DiffValueProps {
  value: unknown;
  /** Muted styling for the "before" side. */
  tone?: 'before' | 'after';
}

/**
 * One side of a change. Structured values (nested lines, extras) get their OWN
 * horizontally-scrollable code block so a wide payload never widens the page
 * (AC-13-44); scalars clamp with the full text always reachable.
 */
export function DiffValue({ value, tone = 'after' }: DiffValueProps) {
  const display: DiffValueDisplay = formatDiffValue(value);

  if (display.kind === 'structured') {
    return (
      <pre
        className={cn(
          'max-h-48 overflow-auto rounded-md bg-muted px-2 py-1.5 font-mono text-xs',
          tone === 'before' && 'text-muted-foreground',
        )}
      >
        {display.text}
      </pre>
    );
  }

  if (display.kind === 'empty') {
    return <span className="text-sm text-muted-foreground">{display.text}</span>;
  }

  return (
    <ClampedText
      text={display.text}
      lines={3}
      className={cn(
        'text-sm break-words',
        tone === 'before' ? 'text-muted-foreground' : 'text-foreground font-medium',
      )}
    />
  );
}

export interface RecordDiffProps {
  /** The staged record's raw `diff` — CHANGED FIELDS ONLY, as the server sends it. */
  diff: Record<string, unknown> | null;
  /** Canonical payload, used only to expand a first-seen record's "nothing → value". */
  canonical?: Record<string, unknown> | null;
  className?: string;
}

/**
 * Per-record before → after diff (AC-13-12).
 *
 * Renders ONLY the fields that actually changed — the server omits the rest and
 * nothing here re-derives them. A record with no changes says so plainly rather
 * than rendering an empty grid.
 *
 * Layout stacks on mobile (label / before / after on their own lines) and lays
 * out in columns from `md` up, so there is no horizontal page scroll at 375px.
 */
export function RecordDiff({ diff, canonical, className }: RecordDiffProps) {
  const view = diffForDisplay(diff, canonical);

  if (view.changes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="diff-no-changes">
        No field changes.
      </p>
    );
  }

  return (
    <div className={cn('flex flex-col gap-3', className)} data-testid="record-diff">
      <div
        className={cn(ROW_GRID, 'hidden md:grid text-xs font-medium text-muted-foreground')}
      >
        <span>Field</span>
        <span>Before</span>
        <span aria-hidden="true" />
        <span>After</span>
      </div>

      {view.changes.map((change) => (
        <div
          key={change.field}
          className={cn(ROW_GRID, 'border-t border-border pt-3 md:pt-2')}
          data-testid={`diff-row-${change.field}`}
        >
          <span className="text-sm font-medium text-foreground">
            {humanizeFieldKey(change.field)}
          </span>

          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-xs text-muted-foreground md:hidden">Before</span>
            <DiffValue value={change.from} tone="before" />
          </div>

          <ArrowRight
            className="hidden size-4 shrink-0 self-center text-muted-foreground md:block"
            aria-hidden="true"
          />

          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-xs text-muted-foreground md:hidden">After</span>
            <DiffValue value={change.to} tone="after" />
          </div>
        </div>
      ))}
    </div>
  );
}
