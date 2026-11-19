'use client';

/**
 * Empty, nothing-matches, couldn't-load and no-access states (playbook 0.71.0
 * "Lists > Empty, error and no-access states say what to do next"). Never a
 * bare "No data" or "Something went wrong"; the technical error never shows.
 *
 * - **Nothing here yet:** one line saying what will appear, under a muted
 *   line icon. The way to make the first one is the page's red action, so
 *   there is no second copy of it here.
 * - **Nothing matches:** what was searched and where, and "Clear filters".
 *   The header row and filters stay, so the list never collapses.
 * - **Couldn't load:** what failed, "Try again", and what is still safe.
 * - **No access:** who can open it and the way back.
 * - **Inside a card or panel** (`compact`): the same words, smaller.
 *
 * The state takes the place of the content it replaces and fades in (0.2 s).
 */
import { Ban, CloudOff, Inbox, SearchX, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

export type FxListStateKind = 'empty' | 'no-match' | 'error' | 'no-access';

export interface FxListStateWords {
  /** The things the list holds, plural, lower case ("products"). */
  noun: string;
  /** The page's name, as the side menu says it ("Products"). */
  title: string;
  /** Whether people here can add the first one (via the red action). */
  canCreate?: boolean;
  /** The trashed view of the list. */
  trashed?: boolean;
  /** The text searched for, if any. */
  search?: string;
  /** The one column a text search ran in, if it ran in one column. */
  column?: string;
}

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** The words of each state (pure, so the copy is testable on its own). */
export function fxListStateText(
  kind: FxListStateKind,
  w: FxListStateWords,
): { line: string; safe?: string } {
  switch (kind) {
    case 'empty':
      if (w.trashed) return { line: `Trashed ${w.noun} show here.` };
      return {
        line: w.canCreate ? `${cap(w.noun)} you add show here.` : `${cap(w.noun)} show here as they arrive.`,
      };
    case 'no-match':
      if (w.search && w.column) return { line: `No ${w.noun} match "${w.search}" in ${w.column}.` };
      if (w.search) return { line: `No ${w.noun} match "${w.search}".` };
      return { line: `No ${w.noun} match these filters.` };
    case 'error':
      return { line: `Couldn't load the ${w.noun}.`, safe: 'Your search and filters are kept.' };
    case 'no-access':
      return { line: `Your role can't open ${w.title}.` };
  }
}

const ICONS: Record<FxListStateKind, LucideIcon> = {
  empty: Inbox,
  'no-match': SearchX,
  error: CloudOff,
  'no-access': Ban,
};

export interface FxListStateProps extends FxListStateWords {
  kind: FxListStateKind;
  compact?: boolean;
  onClearFilters?: () => void;
  onRetry?: () => void;
  onBack?: () => void;
  className?: string;
}

export function FxListState({
  kind,
  compact,
  onClearFilters,
  onRetry,
  onBack,
  className,
  ...words
}: FxListStateProps) {
  const { line, safe } = fxListStateText(kind, words);
  const Icon = ICONS[kind];
  const action =
    kind === 'no-match' && onClearFilters
      ? { label: 'Clear filters', onClick: onClearFilters }
      : kind === 'error' && onRetry
        ? { label: 'Try again', onClick: onRetry }
        : kind === 'no-access' && onBack
          ? { label: 'Go back', onClick: onBack }
          : null;

  return (
    <div
      data-fx-list-state={kind}
      role={kind === 'error' || kind === 'no-access' ? 'alert' : 'status'}
      className={cn(
        'flex flex-col items-center justify-center gap-2 text-center animate-in fade-in duration-(--fx-t-hover) ease-(--fx-ease-out)',
        compact ? 'px-4 py-6 text-sm' : 'px-6 py-14 text-base',
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        strokeWidth={1.5}
        className={cn('text-(--fx-ink-3)', compact ? 'size-6' : 'size-9')}
      />
      <p className="max-w-md text-(--fx-ink)">{line}</p>
      {safe && <p className={cn('text-(--fx-ink-3)', compact ? 'text-xs' : 'text-sm')}>{safe}</p>}
      {action && (
        <Button
          type="button"
          variant="fx-text"
          onClick={action.onClick}
          className={cn('text-(--fx-link)', compact ? 'text-xs' : 'text-sm')}
        >
          {action.label}
        </Button>
      )}
    </div>
  );
}

/** Which state a list is in, or null when it shows rows (pure). */
export function fxListStateKind(s: {
  error: string | null;
  errorStatus: number | null;
  isLoading: boolean;
  rowCount: number;
  filtered: boolean;
}): FxListStateKind | null {
  if (s.error && s.errorStatus === 403) return 'no-access';
  if (s.isLoading) return null;
  if (s.error) return 'error';
  if (s.rowCount > 0) return null;
  return s.filtered ? 'no-match' : 'empty';
}
