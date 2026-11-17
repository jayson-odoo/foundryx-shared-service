'use client';

import { useEffect, useRef, useState } from 'react';
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

// One line = a single-line ellipsis: `line-clamp-1` never cuts a single
// unbreakable string (a URL, a long key) with "..." and never overflows
// vertically, so it was clipped mid-letter with no tooltip.
const CLAMP: Record<number, string> = {
  1: 'block min-w-0 overflow-hidden text-ellipsis whitespace-nowrap',
  2: 'line-clamp-2 break-words',
  3: 'line-clamp-3 break-words',
  4: 'line-clamp-4 break-words',
};

export function ClampedText({ text, lines = 3, className }: ClampedTextProps) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Switching to/from the tooltip wrapper remounts the <p>; this effect then
    // re-attaches to the new node (`truncated` dep), and a detached old node
    // (size 0) is ignored rather than flipping `truncated` back.
    const measure = () => {
      if (!el.isConnected) return;
      setTruncated(el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, lines, truncated]);

  const paragraph = (
    <p ref={ref} className={cn(CLAMP[lines], className)}>
      {text}
    </p>
  );

  if (!truncated) return paragraph;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{paragraph}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs whitespace-pre-wrap break-words">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
