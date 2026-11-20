'use client';

import { ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import type { Idea } from '@/types/ideation';

// Stop the row / card click AND any wrapping link's navigation.
const stop = (e: React.MouseEvent) => {
  e.stopPropagation();
  e.preventDefault();
};

export interface VoteCellProps {
  idea: Idea;
  onVote: (idea: Idea, dir: 'up') => void;
  /** A merged child's votes are frozen (AC-94-26/35) - the control renders
   * disabled and never calls `onVote`. */
  disabled?: boolean;
  /** `pill` = the compact inline control; `box` = the bordered vote box
   * (chevron above the count) used on the idea page, list and board. */
  variant?: 'pill' | 'box';
  /** Box size: `md` on the idea page header, `sm` in the list / board. */
  size?: 'sm' | 'md';
}

/**
 * Upvote-only control (plan 19, AC-19-15) - the SAME component the list, the
 * board and the idea form render (issue #94, AC-94-35). No downvote anywhere;
 * the pressed state is the primary (orange) token.
 */
export function VoteCell({
  idea,
  onVote,
  disabled = false,
  variant = 'pill',
  size = 'sm',
}: VoteCellProps) {
  const pressed = idea.myVote === 'up';
  const isBox = variant === 'box';
  return (
    <div
      onClick={stop}
      data-variant={variant}
      data-size={size}
      className={cn('flex items-center', isBox && 'shrink-0')}
    >
      <button
        type="button"
        aria-label={pressed ? 'Cancel upvote' : 'Upvote'}
        aria-pressed={pressed}
        disabled={disabled}
        onClick={() => onVote(idea, 'up')}
        className={cn(
          PRESSED_CLASS,
          'transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          isBox
            ? cn(
                'flex flex-col items-center justify-center rounded-lg border font-semibold tabular-nums',
                size === 'md' ? 'h-14 w-13 text-base' : 'h-12 w-11 text-sm',
                pressed
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-background text-foreground hover:bg-muted',
              )
            : cn(
                'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-sm',
                pressed
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground hover:bg-muted',
              ),
        )}
      >
        <ChevronUp className={isBox && size === 'md' ? 'size-5' : 'size-4'} />
        {idea.upvotes}
      </button>
    </div>
  );
}
