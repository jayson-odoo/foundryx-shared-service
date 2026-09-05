'use client';

import { LoaderCircleIcon, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDebounce } from '@/hooks/use-debounce';
import { cn } from '@/lib/utils';

export interface ListSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  /** `default` (list toolbars) or `sm` (compact - node/form/email palettes). */
  size?: 'default' | 'sm';
}

/**
 * AC-DLA-54 - the one search box for `ResourceList` and the palette search
 * (`SearchSelect`/`MultiSelect` get the same debounce+settling signal
 * applied to their own `CommandInput` leading icon instead, since their
 * filtering happens over an already-loaded option list and swapping out
 * cmdk's own `Input` would drop its keyboard-navigation wiring).
 *
 * The leading icon swaps to a settling spinner while the debounced value
 * still trails the typed value - `useDebounce` at 200ms (not the 300ms
 * default, which is for non-search callers).
 */
export function ListSearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  className,
  ariaLabel,
  size = 'default',
}: ListSearchInputProps) {
  const debounced = useDebounce(value, 200);
  const settling = value !== debounced;
  const compact = size === 'sm';
  const iconSize = compact ? 'size-3.5' : 'size-4';

  return (
    <div className={cn('relative', className)}>
      {settling ? (
        <LoaderCircleIcon
          className={cn('absolute start-2.5 top-1/2 -translate-y-1/2 animate-spin text-muted-foreground', iconSize)}
          data-testid="list-search-settling"
        />
      ) : (
        <Search className={cn('absolute start-2.5 top-1/2 -translate-y-1/2 text-muted-foreground', iconSize)} />
      )}
      <Input
        variant={compact ? 'sm' : 'md'}
        className={cn(compact ? 'ps-8' : 'ps-9', 'pe-9 w-full')}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
      />
      {value && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          mode="icon"
          className="absolute end-1 top-1/2 -translate-y-1/2 size-7"
          onClick={() => onChange('')}
          aria-label="Clear search"
        >
          <X />
        </Button>
      )}
    </div>
  );
}
