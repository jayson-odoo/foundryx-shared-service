'use client';

/**
 * The pager under a Foundryx UIUX list (playbook 0.71.0 "Long lists load in
 * pages"): at the right, ‹, the page numbers (first, last and two either side
 * of the current one, with … between) and ›; rows per page (25, 50, 100) at
 * its left; "Showing 51-100 of 12,340" counts every match. Phones get the same
 * pager, centred, with only ‹, "Page 3 of 247" and ›.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import { FX_PAGE_SIZES, fxPageNumbers, fxShowingText } from './list-logic';

export interface FxPagerProps {
  /** 0-based. */
  pageIndex: number;
  pageSize: number;
  total: number;
  onPage: (pageIndex: number) => void;
  onPageSize: (size: number) => void;
}

export function FxPager({ pageIndex, pageSize, total, onPage, onPageSize }: FxPagerProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(pageIndex + 1, pageCount);
  const numbers = fxPageNumbers(current, pageCount);
  const sizes = FX_PAGE_SIZES.includes(pageSize as (typeof FX_PAGE_SIZES)[number])
    ? FX_PAGE_SIZES
    : [...FX_PAGE_SIZES, pageSize].sort((a, b) => a - b);

  const arrow = (dir: 'prev' | 'next') => {
    const target = dir === 'prev' ? pageIndex - 1 : pageIndex + 1;
    const disabled = dir === 'prev' ? current <= 1 : current >= pageCount;
    return (
      <Button
        type="button"
        variant="ghost"
        mode="icon"
        size="sm"
        aria-label={dir === 'prev' ? 'Previous page' : 'Next page'}
        disabled={disabled}
        onClick={() => onPage(target)}
        className="size-9 rounded-(--fx-r-pill) text-(--fx-ink-2)"
      >
        {dir === 'prev' ? <ChevronLeft className="size-4" /> : <ChevronRight className="size-4" />}
      </Button>
    );
  };

  return (
    <nav
      aria-label="Pages"
      data-fx-pager=""
      className="flex w-full flex-col items-center gap-2 px-3 py-3 text-sm text-(--fx-ink-2) sm:flex-row sm:justify-between"
    >
      <span data-fx-showing="" aria-live="polite" className="hidden text-(--fx-ink-3) sm:inline">
        {fxShowingText(pageIndex, pageSize, total)}
      </span>
      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-2 sm:flex">
          <span className="text-(--fx-ink-3)">Rows per page</span>
          <SearchSelect
            className="h-8 w-20"
            ariaLabel="Rows per page"
            options={sizes.map((n) => ({ label: String(n), value: String(n) }))}
            value={String(pageSize)}
            onChange={(v) => onPageSize(Number(v))}
          />
        </div>
        <div className="flex items-center gap-1">
          {arrow('prev')}
          <span className="px-2 sm:hidden" data-fx-page-of="">
            Page {current} of {pageCount.toLocaleString('en-US')}
          </span>
          <ul className="hidden items-center gap-1 sm:flex">
            {numbers.map((n, i) =>
              n === 'gap' ? (
                <li key={`gap-${i}`} aria-hidden="true" className="px-1 text-(--fx-ink-3)">
                  …
                </li>
              ) : (
                <li key={n}>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Page ${n}`}
                    aria-current={n === current ? 'page' : undefined}
                    onClick={() => onPage(n - 1)}
                    className={cn(
                      'h-9 min-w-9 rounded-(--fx-r-pill) px-2 tabular-nums',
                      n === current
                        ? 'bg-(--fx-link-bg) font-semibold text-(--fx-link)'
                        : 'text-(--fx-ink-2)',
                    )}
                  >
                    {n.toLocaleString('en-US')}
                  </Button>
                </li>
              ),
            )}
          </ul>
          {arrow('next')}
        </div>
      </div>
    </nav>
  );
}
