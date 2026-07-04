'use client';

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export interface OverflowPillsProps<T> {
  items: T[];
  keyFor: (item: T) => string;
  /** Render a single pill (used in the row, the measurement layer, and the popover). */
  renderPill: (item: T) => ReactNode;
  emptyText?: string;
  /** Gap between pills (px). */
  gap?: number;
  /** Reserved width (px) for the "+N" badge when overflowing. */
  morePillWidth?: number;
  className?: string;
}

/**
 * Single-row pill list that fits as many pills as the available width allows,
 * collapsing the remainder into a "+N" popover. Recomputes on container resize
 * so it's fully dynamic to column/screen width (design principle). Reusable for
 * any list cell that shows a growing set of tags (roles, labels, …).
 */
export function OverflowPills<T>({
  items,
  keyFor,
  renderPill,
  emptyText = '—',
  gap = 4,
  morePillWidth = 44,
  className,
}: OverflowPillsProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(items.length);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const measure = measureRef.current;
    if (!container || !measure) return;

    const recompute = () => {
      const avail = container.clientWidth;
      const widths = Array.from(measure.children).map((c) => (c as HTMLElement).offsetWidth);
      if (!widths.length) {
        setVisible(0);
        return;
      }
      let used = 0;
      let count = 0;
      for (let i = 0; i < widths.length; i++) {
        const w = widths[i] + (i > 0 ? gap : 0);
        const reserve = i < widths.length - 1 ? morePillWidth + gap : 0; // room for "+N"
        if (used + w + reserve <= avail) {
          used += w;
          count++;
        } else {
          break;
        }
      }
      setVisible(count);
    };

    const ro = new ResizeObserver(recompute);
    ro.observe(container);
    recompute();
    return () => ro.disconnect();
  }, [items, gap, morePillWidth]);

  if (!items.length) return <span className="text-muted-foreground">{emptyText}</span>;

  const shown = items.slice(0, visible);
  const hidden = items.slice(visible);

  return (
    <div ref={containerRef} className={cn('flex w-full items-center', className)}>
      {/* Measurement layer — all pills, removed from flow, used only to size. */}
      <div
        ref={measureRef}
        aria-hidden
        className="pointer-events-none absolute -z-10 flex items-center opacity-0"
        style={{ gap }}
      >
        {items.map((it) => (
          <span key={keyFor(it)}>{renderPill(it)}</span>
        ))}
      </div>

      {/* Visible pills. */}
      <div className="flex items-center overflow-hidden" style={{ gap }}>
        {shown.map((it) => (
          <span key={keyFor(it)} className="shrink-0">
            {renderPill(it)}
          </span>
        ))}
      </div>

      {hidden.length > 0 && (
        <Popover>
          <PopoverTrigger asChild>
            <Badge
              variant="secondary"
              appearance="outline"
              size="sm"
              className="ms-1 shrink-0 cursor-pointer"
              onClick={(e) => e.stopPropagation()}
            >
              +{hidden.length}
            </Badge>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-auto max-w-xs p-2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex flex-wrap gap-1">
              {items.map((it) => (
                <span key={keyFor(it)}>{renderPill(it)}</span>
              ))}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
