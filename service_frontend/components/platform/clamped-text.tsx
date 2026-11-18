'use client';

import { useCallback, useEffect, useState } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/**
 * Line-clamped text that ALWAYS offers the full content when it actually
 * truncates (house rule: truncation must never hide text with no way to read
 * it). Detects real overflow - short text renders plain, no tooltip noise.
 */
export interface ClampedTextProps {
  text: string;
  /** Tailwind line-clamp count (default 3). */
  lines?: 1 | 2 | 3 | 4;
  className?: string;
}

const CLAMP: Record<number, string> = {
  // One line = a sideways cut with "...": in a one-line table cell the text
  // overflows to the right, which a vertical line-clamp never shows (crew
  // pass 70e96f2b).
  1: 'truncate',
  2: 'line-clamp-2 break-words',
  3: 'line-clamp-3 break-words',
  4: 'line-clamp-4 break-words',
};

export function ClampedText({ text, lines = 3, className }: ClampedTextProps) {
  // A callback ref, not useRef: once the text truncates the <p> remounts inside
  // the tooltip trigger, and the observer must follow the NEW node (a detached
  // one measures 0 and would switch the tooltip back off).
  const [el, setEl] = useState<HTMLParagraphElement | null>(null);
  const [truncated, setTruncated] = useState(false);

  const measure = useCallback(() => {
    if (!el) return;
    setTruncated(el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1);
  }, [el]);

  // Re-measure on text / clamp changes and on every resize of the mounted node.
  useEffect(() => {
    if (!el) return;
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el, measure, text, lines]);

  const paragraph = (
    // A table settles its column widths after mount without resizing the text
    // box itself, so the overflow is re-checked on hover too, the moment the
    // full text is wanted (crew pass 70e96f2b).
    <p ref={setEl} onPointerEnter={measure} className={cn(CLAMP[lines], className)}>
      {text}
    </p>
  );

  if (!truncated) return paragraph;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{paragraph}</TooltipTrigger>
      <TooltipContent side="bottom" align="start" className="max-w-xs whitespace-pre-wrap break-words">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
