'use client';

import { ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import type { Idea } from '@/types/ideation';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface VoteCellProps {
  idea: Idea;
  onVote: (idea: Idea, dir: 'up' | 'down') => void;
  /** A merged child's votes are frozen (AC-94-26/35) - both buttons render
   * disabled and never call `onVote`. */
  disabled?: boolean;
}

/**
 * Up/down vote control - the SAME component the list and the idea form render
 * (issue #94, ideation round 2, AC-94-35), extracted from
 * `use-ideas-list-config.tsx` so no parallel vote control ever forks.
 */
export function VoteCell({ idea, onVote, disabled = false }: VoteCellProps) {
  return (
    <div onClick={stop} className="flex items-center gap-1">
      <button
        type="button"
        aria-label={idea.myVote === 'up' ? 'Cancel upvote' : 'Upvote'}
        aria-pressed={idea.myVote === 'up'}
        disabled={disabled}
        onClick={() => onVote(idea, 'up')}
        className={cn(
          PRESSED_CLASS,
          'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          idea.myVote === 'up'
            ? 'bg-emerald-50 font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400'
            : 'text-muted-foreground hover:bg-muted',
        )}
      >
        <ChevronUp className="size-4" />
        {idea.upvotes}
      </button>
      <button
        type="button"
        aria-label={idea.myVote === 'down' ? 'Cancel downvote' : 'Downvote'}
        aria-pressed={idea.myVote === 'down'}
        disabled={disabled}
        onClick={() => onVote(idea, 'down')}
        className={cn(
          PRESSED_CLASS,
          'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          idea.myVote === 'down'
            ? 'bg-rose-50 font-medium text-rose-700 dark:bg-rose-950/40 dark:text-rose-400'
            : 'text-muted-foreground hover:bg-muted',
        )}
      >
        <ChevronDown className="size-4" />
        {idea.downvotes}
      </button>
    </div>
  );
}
