'use client';

/**
 * A column header under the Foundryx UIUX switch (playbook 0.71.0 "Lists",
 * "Header search, filter and sort").
 *
 * - Hovering shows a Search (or Filter) icon and a Sort icon over the
 *   header's free end on a soft fade, so the column never widens.
 * - Clicking the header (or the Search/Filter icon) filters by the column's
 *   kind: text lays the search box over the header ("Search Client"); dates
 *   open a From and To range, status-like columns open ticks, each in a small
 *   panel under the header with Clear. A header with nothing to search sorts
 *   when clicked.
 * - The Sort icon goes up, then down, then back to the list's own order.
 * - At rest a filtered or sorted column never covers its name: the name turns
 *   link-blue and a small arrow in the header's padding shows the direction.
 * - Esc closes; an empty text search turns back into the header.
 */
import { useEffect, useRef, useState } from 'react';
import type { Column } from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ArrowUpDown, Filter, Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover as PopoverPrimitive } from 'radix-ui';
import { Popover, PopoverContent } from '@/components/ui/popover';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  DateRangePicker,
  resolvePresetRange,
  type DateRangePreset,
} from '@/components/platform/date-range-picker';
import { useFxListHeader, type FxListHeaderContextValue } from './header-context';
import { isEmptyHeaderValue, type FxHeaderValue } from './list-logic';

/** Typing pause before a header search reaches the list. */
const SEARCH_PAUSE_MS = 250;

export interface FxColumnHeaderProps<TData, TValue> {
  column: Column<TData, TValue>;
  title?: string;
}

/** Inside a Foundryx UIUX list only (the caller checks the context). */
export function FxColumnHeader<TData, TValue>({
  column,
  title = '',
}: FxColumnHeaderProps<TData, TValue>) {
  const ctx = useFxListHeader() as FxListHeaderContextValue;
  const kind = ctx.searchOn ? ctx.kindOf(column.id) : null;
  const value = ctx.valueOf(column.id);
  const filtered = !isEmptyHeaderValue(value);
  const canSort = ctx.sortOn && column.getCanSort();
  const sortDir =
    ctx.sort?.id === column.id ? (ctx.sort.desc ? 'desc' : 'asc') : null;
  const active = filtered || sortDir !== null;

  const [open, setOpen] = useState(false);
  const label = title || column.id;
  const actionLabel =
    kind === 'text' ? `Search ${label}` : kind ? `Filter ${label}` : `Sort by ${label}`;

  const onHeaderClick = () => {
    if (kind) setOpen(true);
    else if (canSort) ctx.cycleSort(column.id);
  };

  if (kind === 'text' && open) {
    return (
      <HeaderSearch
        label={label}
        initial={value?.kind === 'text' ? value.text : ''}
        onChange={(text) =>
          ctx.setValue(column.id, text.trim() ? { kind: 'text', text } : undefined)
        }
        onClose={() => setOpen(false)}
      />
    );
  }

  const header = (
    <span className="flex min-w-0 items-center">
      <button
        type="button"
        data-fx-header-label=""
        aria-label={kind || canSort ? actionLabel : undefined}
        aria-haspopup={kind === 'date' || kind === 'status' ? 'dialog' : undefined}
        disabled={!kind && !canSort}
        onClick={onHeaderClick}
        className={cn(
          'min-w-0 cursor-pointer text-start text-[0.8125rem] font-semibold disabled:cursor-default',
          'break-words',
          active ? 'text-(--fx-link)' : 'text-(--fx-ink-2)',
          PRESSED_CLASS,
        )}
      >
        {title}
      </button>
      {sortDir && (
        <span
          aria-hidden="true"
          data-fx-sort-arrow={sortDir}
          className="absolute end-1 top-1/2 -translate-y-1/2 text-(--fx-link)"
        >
          {sortDir === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
        </span>
      )}
      {(kind || canSort) && (
        <span
          data-fx-header-tools=""
          className="pointer-events-none absolute inset-y-0 end-0 flex items-center gap-0.5 bg-gradient-to-l from-(--fx-surface) from-60% to-transparent ps-5 pe-1 opacity-0 transition-opacity duration-(--fx-t-hover) ease-(--fx-ease-out) group-hover/fxh:pointer-events-auto group-hover/fxh:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100"
        >
          {kind && (
            <Button
              type="button"
              variant="ghost"
              mode="icon"
              size="sm"
              aria-label={actionLabel}
              className="size-6 text-(--fx-ink-3) hover:text-(--fx-ink)"
              onClick={() => setOpen(true)}
            >
              {kind === 'text' ? <Search className="size-3.5" /> : <Filter className="size-3.5" />}
            </Button>
          )}
          {canSort && (
            <Button
              type="button"
              variant="ghost"
              mode="icon"
              size="sm"
              aria-label={`Sort by ${label}`}
              className="size-6 text-(--fx-ink-3) hover:text-(--fx-ink)"
              onClick={() => ctx.cycleSort(column.id)}
            >
              {sortDir === 'asc' ? (
                <ArrowUp className="size-3.5" />
              ) : sortDir === 'desc' ? (
                <ArrowDown className="size-3.5" />
              ) : (
                <ArrowUpDown className="size-3.5" />
              )}
            </Button>
          )}
        </span>
      )}
    </span>
  );

  if (kind !== 'date' && kind !== 'status') return header;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Anchor asChild>{header}</PopoverPrimitive.Anchor>
      <PopoverContent
        align="start"
        aria-label={actionLabel}
        className="fx-see-through w-auto rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface)/50 p-3 text-(--fx-ink)"
      >
        {kind === 'date' ? (
          <DateFilter
            value={value?.kind === 'date' ? value : undefined}
            timeZone={ctx.timeZone}
            onChange={(next) => ctx.setValue(column.id, next)}
          />
        ) : (
          <StatusFilter
            options={ctx.optionsOf(column.id)}
            value={value?.kind === 'status' ? value.values : []}
            onChange={(values) =>
              ctx.setValue(column.id, values.length ? { kind: 'status', values } : undefined)
            }
          />
        )}
        <div className="mt-2 flex justify-end">
          <Button
            type="button"
            variant="fx-text"
            size="sm"
            disabled={!filtered}
            onClick={() => ctx.setValue(column.id, undefined)}
          >
            Clear
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** The list's search box laid over the header, exactly its width. */
function HeaderSearch({
  label,
  initial,
  onChange,
  onClose,
}: {
  label: string;
  initial: string;
  onChange: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(initial);
  const settled = useDebounce(text, SEARCH_PAUSE_MS);
  const inputRef = useRef<HTMLInputElement>(null);
  const sent = useRef(initial);
  const send = (value: string) => {
    if (value === sent.current) return;
    sent.current = value;
    onChange(value);
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    send(settled);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the settled text sends
  }, [settled]);

  return (
    <input
      ref={inputRef}
      type="search"
      data-fx-header-search=""
      aria-label={`Search ${label}`}
      placeholder={`Search ${label}`}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          send(text);
          onClose();
        }
        if (e.key === 'Enter') send(text);
      }}
      onBlur={() => {
        send(text);
        onClose();
      }}
      className="absolute inset-0 z-(--fx-z-pop) w-full rounded-(--fx-r-m) border border-(--fx-link) bg-(--fx-surface) px-3 text-sm text-(--fx-ink) outline-hidden placeholder:text-(--fx-ink-3)"
    />
  );
}

function DateFilter({
  value,
  timeZone,
  onChange,
}: {
  value: { from: string; to: string } | undefined;
  timeZone: string;
  onChange: (value: FxHeaderValue | undefined) => void;
}) {
  const [preset, setPreset] = useState<DateRangePreset>('custom');
  // An empty filter starts the picker on the last 7 days, like the Filters
  // panel's range does, but filters nothing until a range is picked.
  const shown = value ?? resolvePresetRange('last7', timeZone);
  return (
    <DateRangePicker
      className="w-full sm:flex-row"
      timeZone={timeZone}
      value={{ preset: value ? preset : 'last7', from: shown.from, to: shown.to }}
      onChange={(next) => {
        setPreset(next.preset);
        onChange({ kind: 'date', from: next.from, to: next.to });
      }}
    />
  );
}

function StatusFilter({
  options,
  value,
  onChange,
}: {
  options: { label: string; value: string }[];
  value: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <ul className="flex max-h-72 min-w-44 flex-col gap-1 overflow-y-auto">
      {options.map((option) => {
        const checked = value.includes(option.value);
        return (
          <li key={option.value}>
            <label className="flex cursor-pointer items-center gap-2 rounded-(--fx-r-s) px-1 py-1 text-sm hover:bg-(--fx-link-bg)">
              <Checkbox
                checked={checked}
                onCheckedChange={(c) =>
                  onChange(
                    c
                      ? [...value, option.value]
                      : value.filter((v) => v !== option.value),
                  )
                }
              />
              {option.label}
            </label>
          </li>
        );
      })}
    </ul>
  );
}
