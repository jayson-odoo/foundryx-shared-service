'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDebounce } from '@/hooks/use-debounce';
import { cn } from '@/lib/utils';

/** T6 fix round 1 item 7 - the spinner only ever SHOWS once it's been due for
 * at least this long; a settle/fetch that resolves faster than this never
 * flashes it at all. */
const SETTLING_SHOW_DELAY_MS = 250;

export interface ListSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  /** `default` (list toolbars) or `sm` (compact - node/form/email palettes). */
  size?: 'default' | 'sm';
  /**
   * T6 fix round 1 item 7 - an additional "still fetching" signal from the
   * caller (`ResourceList` passes `list.isLoading`) that keeps the spinner
   * gated the same way as the typed-vs-debounced settling state. Callers
   * with no such signal (the palette search) simply omit it.
   */
  busy?: boolean;
}

/**
 * AC-DLA-54 - the one search box for `ResourceList` and the palette search.
 * `SearchSelect`/`MultiSelect` (built on `CommandInput`) filter an already
 * loaded, in-memory option list SYNCHRONOUSLY - no fetch to wait on - so
 * their leading icon never shows a settling indicator at all (T6 fix
 * round 1 item 8; `components/ui/command.tsx`).
 *
 * The leading icon swaps to a settling spinner while the debounced value
 * still trails the typed value - `useDebounce` at 200ms (not the 300ms
 * default, which is for non-search callers; see the matching 200ms comment
 * in `hooks/use-resource-list.ts` - the two are tuned to settle together).
 *
 * T6 fix round 1 item 7: `settling` alone flashed a Search->Loader->Search
 * glyph swap on every keystroke pause, turning OFF exactly when the list's
 * own debounce fires the request (so the spinner was gone the instant the
 * fetch actually started). The glyph now only shows once `settling || busy`
 * has been continuously true for `SETTLING_SHOW_DELAY_MS` - fast typing and
 * sub-250ms fetches never show it at all, only a genuinely slow one does.
 */
export function ListSearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  className,
  ariaLabel,
  size = 'default',
  busy = false,
}: ListSearchInputProps) {
  const debounced = useDebounce(value, 200);
  const settling = value !== debounced;
  const compact = size === 'sm';
  const iconSize = compact ? 'size-3.5' : 'size-4';

  const active = settling || busy;
  const [showSettling, setShowSettling] = useState(false);
  useEffect(() => {
    if (!active) {
      setShowSettling(false);
      return;
    }
    const timer = setTimeout(() => setShowSettling(true), SETTLING_SHOW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [active]);

  return (
    <div className={cn('relative', className)}>
      {/* Both glyphs stay mounted at the same spot so `motion-reduce:hidden`
          on the spinner reveals the static Search icon underneath instead of
          leaving an empty slot for a reduced-motion reader. */}
      <Search
        className={cn(
          'absolute start-2.5 top-1/2 -translate-y-1/2 text-muted-foreground',
          showSettling && 'hidden motion-reduce:block',
          iconSize,
        )}
      />
      {showSettling && (
        <LoaderCircleIcon
          className={cn(
            'absolute start-2.5 top-1/2 -translate-y-1/2 animate-spin motion-reduce:hidden text-muted-foreground',
            iconSize,
          )}
          data-testid="list-search-settling"
        />
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
