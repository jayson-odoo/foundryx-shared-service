'use client';

/**
 * Star rating input (plan sprint-3/01) - a 1..max clickable star row, keyboard
 * accessible (arrow keys move the value, the group is a radiogroup). The answer
 * is the integer count; 0 = unset.
 */
import { Star } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface RatingInputProps {
  max: number;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  ariaLabel?: string;
}

export function RatingInput({ max, value, onChange, disabled, ariaLabel }: RatingInputProps) {
  const stars = Array.from({ length: Math.max(1, max) }, (_, i) => i + 1);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault();
      onChange(Math.min(max, value + 1));
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault();
      onChange(Math.max(0, value - 1));
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={onKeyDown}
      className="inline-flex items-center gap-1 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-md"
    >
      {stars.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n}`}
          disabled={disabled}
          onClick={() => onChange(value === n ? 0 : n)}
          className="p-0.5 disabled:cursor-not-allowed"
        >
          <Star
            className={cn(
              'size-6 transition-colors',
              n <= value ? 'fill-primary text-primary' : 'text-muted-foreground/40',
            )}
          />
        </button>
      ))}
    </div>
  );
}
