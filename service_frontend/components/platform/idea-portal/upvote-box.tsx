'use client';

import { ChevronUp } from 'lucide-react';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';

export interface UpvoteBoxProps {
  count: number;
  voted: boolean;
  onVote?: () => void;
  size?: 'sm' | 'lg';
  disabled?: boolean;
}

/** The portal's upvote box (one upvote per signed-in person, toggles). */
export function UpvoteBox({ count, voted, onVote, size = 'sm', disabled }: UpvoteBoxProps) {
  return (
    <button
      type="button"
      aria-pressed={voted}
      aria-label={voted ? `Remove upvote (${count})` : `Upvote (${count})`}
      disabled={disabled || !onVote}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onVote?.();
      }}
      className={cn(
        PRESSED_CLASS,
        'flex shrink-0 flex-col items-center justify-center rounded-md border bg-background transition-colors',
        size === 'lg' ? 'h-16 w-14 border-2 text-lg' : 'h-12 w-10 text-xs',
        voted ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:border-primary/60',
        'disabled:cursor-default disabled:opacity-100',
      )}
    >
      <ChevronUp className={size === 'lg' ? 'size-4' : 'size-3.5'} aria-hidden />
      <span className="font-semibold">{count}</span>
    </button>
  );
}
