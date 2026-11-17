'use client';

import { useEffect, useState } from 'react';
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
  1: 'line-clamp-1',
  2: 'line-clamp-2',
  3: 'line-clamp-3',
  4: 'line-clamp-4',
};

export function ClampedText({ text, lines = 3, className }: ClampedTextProps) {
  // A callback ref, not useRef: once the text truncates the <p> remounts inside
  // the tooltip trigger, and the observer must follow the NEW node (a detached
  // one measures 0 and would switch the tooltip back off).
  const [el, setEl] = useState<HTMLParagraphElement | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    if (!el) return;
    const measure = () => setTruncated(el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el, text, lines]);

  const paragraph = (
    <p ref={setEl} className={cn(CLAMP[lines], className)}>
      {text}
    </p>
  );

  if (!truncated) return paragraph;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{paragraph}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs whitespace-pre-wrap">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}
