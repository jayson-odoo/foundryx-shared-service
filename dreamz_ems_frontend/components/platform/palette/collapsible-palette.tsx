'use client';

/**
 * Generic grouped / collapsible / searchable palette — the house node-palette
 * pattern (form-builder D7), shared across the form, email, and canvas editors.
 * Collapsed-by-default category sections with counts + a search box that
 * auto-expands matching categories. The CALLER renders each item (draggable
 * button, click button, …) via `renderItem`; this owns search + collapse only.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';

export interface PaletteCategory<T extends string> {
  id: string;
  label: string;
  types: T[];
}

export interface CollapsiblePaletteProps<T extends string> {
  categories: PaletteCategory<T>[];
  /** Display label for a type — used for search matching. */
  labelFor: (type: T) => string;
  /** Render one palette entry (the caller owns drag/click behaviour). */
  renderItem: (type: T) => ReactNode;
  searchPlaceholder?: string;
  testId?: string;
  /** Category ids open on first render (default: all collapsed). */
  defaultOpenIds?: string[];
}

export function CollapsiblePalette<T extends string>({
  categories,
  labelFor,
  renderItem,
  searchPlaceholder = 'Search',
  testId = 'palette',
  defaultOpenIds = [],
}: CollapsiblePaletteProps<T>) {
  const [query, setQuery] = useState('');
  const [openIds, setOpenIds] = useState<Set<string>>(new Set(defaultOpenIds));

  const term = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!term) return categories;
    return categories
      .map((c) => ({ ...c, types: c.types.filter((t) => labelFor(t).toLowerCase().includes(term)) }))
      .filter((c) => c.types.length > 0);
  }, [term, categories, labelFor]);

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <div className="relative">
        <Search className="pointer-events-none absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          className="h-8 ps-8 text-xs"
        />
      </div>
      <div className="flex flex-col gap-1">
        {filtered.map((category) => {
          const open = term ? true : openIds.has(category.id);
          return (
            <div key={category.id} className="rounded-md">
              <button
                type="button"
                data-testid={`palette-category-${category.id}`}
                onClick={() => toggle(category.id)}
                className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
              >
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                <span className="flex-1 text-start">{category.label}</span>
                <span className="text-[10px] font-normal">{category.types.length}</span>
              </button>
              {open && (
                <div className="flex flex-col gap-1 px-1 pb-1.5 pt-0.5">
                  {category.types.map((type) => (
                    <div key={type}>{renderItem(type)}</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && (
          <p className="px-1.5 py-2 text-xs text-muted-foreground">No matches.</p>
        )}
      </div>
    </div>
  );
}
