'use client';
/* eslint-disable jsx-a11y/role-has-required-aria-props -- the combobox's aria-controls is added by PopoverTrigger at run time */

/**
 * The Foundryx UIUX searchable dropdown (playbook 0.71.0 "Dropdowns" and
 * "Searchable dropdowns"). `SearchSelect` renders it while the switch is on,
 * with the same props, so every dropdown on every page gets it.
 *
 * Every dropdown is searchable here, whatever its size: Shared Service's own
 * rule wins over the playbook's ~12-option threshold (playbook-uiux.md).
 */
import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { SearchSelectOption, SearchSelectProps } from '@/components/platform/search-select/search-select';
import { FX_FIELD, FX_MENU, FX_MENU_ROW } from './classes';
import {
  FX_MENU_LIMIT,
  FxHighlight,
  fxMatches,
  narrowText,
  nothingMatchesText,
  queryWords,
  usePausedQuery,
} from './menu-search';

/** The closed field: looks like every other field, a small grey chevron on the right. */
export const FX_SELECT_TRIGGER =
  'flex h-8.5 w-full items-center justify-between gap-2 px-3 text-start text-[0.8125rem] pointer-coarse:text-base font-normal';

/** The open list's frame and its search box. */
export const FX_MENU_COMMAND =
  'bg-transparent [&_[cmdk-input-wrapper]]:border-(--fx-line) [&_[cmdk-input-wrapper]_svg]:text-(--fx-ink-3) ' +
  '[&_[cmdk-input]]:text-(--fx-ink) [&_[cmdk-input]]:placeholder:text-(--fx-ink-3) ' +
  '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-(--fx-ink-3)';

export function FxSearchSelect({
  options,
  groups,
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches.',
  disabled = false,
  className,
  ariaLabel,
  allowCustom = false,
  customLabel,
  onQueryChange,
  loading = false,
  total,
  noun,
}: SearchSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const sendQuery = usePausedQuery(onQueryChange);
  const typedRef = useRef('');
  const sendRef = useRef(sendQuery);
  sendRef.current = sendQuery;
  // Closing (by Esc, a pick or outside) clears the search, and a caller
  // that fetches hears the reset too, so the next open starts fresh.
  useEffect(() => {
    if (open) return;
    setQuery('');
    if (typedRef.current) {
      typedRef.current = '';
      sendRef.current('');
    }
  }, [open]);

  const allGroups: { label?: string; options: SearchSelectOption[] }[] =
    groups ?? [{ label: undefined, options: options ?? [] }];
  const flat = allGroups.flatMap((g) => g.options);
  const selected = flat.find((o) => o.value === value);
  const triggerLabel = selected ? selected.label : allowCustom && value ? value : placeholder;

  const words = queryWords(query);
  // A caller that fetches as you type already sent back the matching page.
  const filtered = allGroups
    .map((g) => ({ ...g, options: onQueryChange ? g.options : g.options.filter((o) => fxMatches(o, words)) }))
    .filter((g) => g.options.length > 0);
  const matchCount = filtered.reduce((n, g) => n + g.options.length, 0);
  let budget = FX_MENU_LIMIT;
  const shown = filtered
    .map((g) => {
      const take = g.options.slice(0, Math.max(0, budget));
      budget -= take.length;
      return { ...g, options: take };
    })
    .filter((g) => g.options.length > 0);
  const totalResults = Math.max(total ?? 0, matchCount);
  const trimmed = query.trim();
  const exact = flat.some(
    (o) => o.label.toLowerCase() === trimmed.toLowerCase() || o.value === trimmed,
  );
  const showCreate = allowCustom && trimmed.length > 0 && !exact;

  const pick = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel}
          disabled={disabled}
          data-fx-field=""
          title={selected || (allowCustom && value) ? triggerLabel : undefined}
          className={cn(PRESSED_CLASS, FX_FIELD, FX_SELECT_TRIGGER, className)}
        >
          <span
            className={cn(
              'min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap',
              !selected && !(allowCustom && value) && 'text-(--fx-ink-3)',
            )}
          >
            {triggerLabel}
          </span>
          <ChevronDown className="size-4 shrink-0 text-(--fx-ink-3)" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className={cn(FX_MENU, 'w-auto min-w-(--radix-popover-trigger-width) max-w-[min(32rem,calc(100vw-2rem))] p-0')}
        align="start"
      >
        <Command shouldFilter={false} className={FX_MENU_COMMAND}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(v) => {
              setQuery(v);
              typedRef.current = v;
              sendQuery(v);
            }}
          />
          <CommandList
            aria-busy={loading || undefined}
            className={cn(
              'max-h-[min(20rem,50vh)] p-1 transition-opacity duration-(--fx-t-hover)',
              loading && 'opacity-50',
            )}
          >
            {matchCount === 0 && (
              <div className="px-2 py-4 text-center text-sm text-(--fx-ink-2)">
                {trimmed ? nothingMatchesText(trimmed, noun) : emptyText}
              </div>
            )}
            {shown.map((group, groupIndex) => (
              <CommandGroup key={group.label ?? groupIndex} heading={group.label}>
                {group.options.map((option) => {
                  const chosen = option.value === value;
                  return (
                    <CommandItem
                      key={option.value}
                      value={`${option.value}`}
                      onSelect={() => pick(option.value)}
                      className={cn(FX_MENU_ROW, 'items-start')}
                    >
                      <Check
                        aria-hidden="true"
                        className={cn('mt-0.5 size-4 shrink-0 text-(--fx-link)', chosen ? 'opacity-100' : 'opacity-0')}
                      />
                      <span className="flex min-w-0 flex-col">
                        <span className={cn(chosen && 'font-semibold')}>
                          <FxHighlight text={option.label} words={words} />
                        </span>
                        {option.description && (
                          <span className="text-xs text-(--fx-ink-3)">
                            <FxHighlight text={option.description} words={words} />
                          </span>
                        )}
                      </span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ))}
            {totalResults > FX_MENU_LIMIT && (
              <div className="px-2 py-2 text-xs text-(--fx-ink-3)">{narrowText(totalResults)}</div>
            )}
            {showCreate && (
              <CommandGroup>
                <CommandItem
                  value="__fx_create__"
                  onSelect={() => pick(trimmed)}
                  className={cn(FX_MENU_ROW, 'font-medium text-(--fx-link)')}
                >
                  <Plus aria-hidden="true" className="size-4 shrink-0" />
                  {customLabel ? customLabel(trimmed) : `Create "${trimmed}"`}
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
