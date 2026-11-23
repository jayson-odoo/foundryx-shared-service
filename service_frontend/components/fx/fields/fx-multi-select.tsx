'use client';
/* eslint-disable jsx-a11y/role-has-required-aria-props -- the combobox's aria-controls is added by PopoverTrigger at run time */

/**
 * The Foundryx UIUX many-choice dropdown (playbook 0.71.0 "Searchable
 * dropdowns > Many choices"): picks become chips inside the field, each with
 * its ×, and the list stays open for the next pick. `MultiSelect` renders it
 * while the switch is on, with the same props.
 */
import { useEffect, useState } from 'react';
import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { MultiSelectProps } from '@/components/platform/multi-select/multi-select';
import { FX_FIELD, FX_MENU, FX_MENU_ROW } from './classes';
import { FxFieldContext, useFxControlName } from './fx-field-context';
import { FX_MENU_COMMAND } from './fx-search-select';
import {
  FX_MENU_LIMIT,
  FxHighlight,
  fxMatches,
  narrowText,
  nothingMatchesText,
  queryWords,
  usePausedQuery,
} from './menu-search';

export function FxMultiSelect({
  options,
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches.',
  size = 'md',
  className,
  disabled = false,
  onQueryChange,
  ariaLabel,
  id,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const naming = useFxControlName({ id, ariaLabel, placeholder });
  const sendQuery = usePausedQuery(onQueryChange);
  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const selected = options.filter((o) => value.includes(o.value));
  const toggle = (v: string) =>
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  const allSelected = options.length > 0 && value.length === options.length;
  const words = queryWords(query);
  const matching = onQueryChange ? options : options.filter((o) => fxMatches(o, words));
  const shown = matching.slice(0, FX_MENU_LIMIT);
  const trimmed = query.trim();

  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          // Named by `ariaLabel`, else the labelled FxField around it, else
          // a `<Label htmlFor>` pointing at `id`; only last by what it asks
          // for (FX-19, fx-field-context.ts).
          {...naming}
          aria-expanded={open}
          disabled={disabled}
          data-fx-field=""
          className={cn(
            PRESSED_CLASS,
            FX_FIELD,
            'flex h-auto min-h-8.5 w-full items-center justify-between gap-1 px-2 py-1 text-start text-[0.8125rem] pointer-coarse:text-base',
            size === 'sm' && 'min-h-7 text-xs',
            className,
          )}
        >
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
            {selected.length === 0 ? (
              <span className="px-1 text-(--fx-ink-3)">{placeholder}</span>
            ) : (
              selected.map((o) => (
                <span
                  key={o.value}
                  data-fx-chip=""
                  className="inline-flex max-w-full items-center gap-0.5 rounded-(--fx-r-pill) bg-(--fx-chip) py-0.5 ps-2 pe-1 text-xs font-medium text-(--fx-chip-ink)"
                >
                  <span className="break-all">{o.label}</span>
                  <span
                    role="presentation"
                    aria-hidden="true"
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      toggle(o.value);
                    }}
                    className="inline-flex size-4 items-center justify-center rounded-full hover:bg-(--fx-line-2)"
                  >
                    <X className="size-3" />
                  </span>
                </span>
              ))
            )}
          </span>
          <ChevronDown className="size-4 shrink-0 text-(--fx-ink-3)" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className={cn(FX_MENU, 'w-auto min-w-(--radix-popover-trigger-width) max-w-[min(32rem,calc(100vw-2rem))] p-0')}
        align="start"
      >
        <FxFieldContext.Provider value={null}>
        <Command shouldFilter={false} className={FX_MENU_COMMAND}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(v) => {
              setQuery(v);
              sendQuery(v);
            }}
          />
          <div className="flex items-center justify-between border-b border-(--fx-line) px-3 py-1.5">
            <span className="text-xs text-(--fx-ink-3)">{value.length} selected</span>
            <button
              type="button"
              className={cn(PRESSED_CLASS, 'text-xs font-medium text-(--fx-link) hover:underline')}
              onClick={() => onChange(allSelected ? [] : options.map((o) => o.value))}
            >
              {allSelected ? 'Clear all' : 'Select all'}
            </button>
          </div>
          <CommandList className="max-h-[min(20rem,50vh)] p-1">
            {matching.length === 0 && (
              <div className="px-2 py-4 text-center text-sm text-(--fx-ink-2)">
                {trimmed ? nothingMatchesText(trimmed) : emptyText}
              </div>
            )}
            <CommandGroup>
              {shown.map((o) => {
                const on = value.includes(o.value);
                return (
                  <CommandItem
                    key={o.value}
                    value={o.value}
                    onSelect={() => toggle(o.value)}
                    className={FX_MENU_ROW}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        'flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-(--fx-line-2)',
                        on && 'border-(--fx-link) bg-(--fx-link) text-white',
                      )}
                    >
                      {on && <Check className="size-3" />}
                    </span>
                    <span className={cn(on && 'font-semibold')}>
                      <FxHighlight text={o.label} words={words} />
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
            {matching.length > FX_MENU_LIMIT && (
              <div className="px-2 py-2 text-xs text-(--fx-ink-3)">{narrowText(matching.length)}</div>
            )}
          </CommandList>
        </Command>
        </FxFieldContext.Provider>
      </PopoverContent>
    </Popover>
  );
}
