'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useFx } from '@/hooks/use-fx';
import { FxSearchSelect } from '@/components/fx/fields/fx-search-select';

export interface SearchSelectOption {
  label: string;
  value: string;
  /** Foundryx UIUX only: one muted second line (a code, a size, a price),
   *  also matched by the search. Ignored with the switch off. */
  description?: string;
}

export interface SearchSelectGroup {
  label: string;
  options: SearchSelectOption[];
}

export interface SearchSelectProps {
  options?: SearchSelectOption[];
  /** Grouped options (section heading per group) - wins over `options`. */
  groups?: SearchSelectGroup[];
  value: string | null | undefined;
  onChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  /** Accessible name for the combobox trigger. */
  ariaLabel?: string;
  /**
   * Foundryx UIUX switch only (ignored with the switch off): the trigger's
   * id, for a visible `<label htmlFor>` that names it. Inside a labelled
   * `FxField` the field's own id and label are used without it.
   */
  id?: string;
  /**
   * Allow committing the typed search text as the value when it matches no
   * option (a combobox with create - e.g. a free dotted mapping source path
   * `Data.0.X`). The listed options stay the discoverable set; a custom value is
   * surfaced as a "Use …" item and shown verbatim on the trigger.
   */
  allowCustom?: boolean;
  /** Label for the create item (default: `Use "<typed>"`). */
  customLabel?: (query: string) => string;
  /**
   * Called with the typed search text on every keystroke, IN ADDITION to the
   * built-in client-side filter over `options` - lets a caller drive a
   * server-searched/debounced options set (e.g. a large contact picker)
   * instead of forking a parallel searchable-select component.
   */
  onQueryChange?: (query: string) => void;
  /** Foundryx UIUX only (ignored with the switch off): the caller is fetching
   *  new results, so the list keeps its last ones, dimmed. */
  loading?: boolean;
  /** Foundryx UIUX only: how many results match in all, when the caller
   *  fetched only a page ("Keep typing to narrow 1,240 results"). */
  total?: number;
  /** Foundryx UIUX only: the plural noun for "No products match "oak"". */
  noun?: string;
}

/**
 * Searchable single-select (combobox) - the system-wide rule (user mandate,
 * sprint-2/01 review): every dropdown over a data-driven list is searchable,
 * like the user/role pickers. Sibling of `MultiSelect` (which additionally
 * does select-all); fixed 2-3-option micro-enums may stay plain Select.
 */
export function SearchSelect(props: SearchSelectProps) {
  // Foundryx UIUX switch: the playbook dropdown while on; today's while off.
  return useFx() ? <FxSearchSelect {...props} /> : <SearchSelectLegacy {...props} />;
}

function SearchSelectLegacy({
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
}: SearchSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // Clear the typed search whenever the popover closes - programmatic closes
  // (an option select calls setOpen(false), which does NOT fire onOpenChange)
  // must reset too, else the next open's text appends to the stale query.
  // A caller filtering on `onQueryChange` hears the reset too, else its list
  // stays narrowed under an empty box (crew pass 4025e5e9).
  const typedRef = useRef('');
  const onQueryChangeRef = useRef(onQueryChange);
  onQueryChangeRef.current = onQueryChange;
  useEffect(() => {
    if (open) return;
    setQuery('');
    if (typedRef.current) {
      typedRef.current = '';
      onQueryChangeRef.current?.('');
    }
  }, [open]);
  const flat = groups ? groups.flatMap((g) => g.options) : (options ?? []);
  const selected = flat.find((o) => o.value === value);
  // A custom (unlisted) value still needs a legible trigger label.
  const triggerLabel = selected
    ? selected.label
    : allowCustom && value
      ? value
      : placeholder;
  const trimmed = query.trim();
  const showCustom =
    allowCustom &&
    trimmed.length > 0 &&
    !flat.some((o) => o.value === trimmed || o.label === trimmed);

  return (
    // modal: inside a Sheet/Dialog the scroll lock otherwise swallows wheel
    // events - the option list wouldn't scroll (sprint-2/02 iteration).
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel}
          disabled={disabled}
          className={cn('w-full justify-between font-normal', className)}
        >
          <span
            className={cn(
              'truncate',
              !selected && !(allowCustom && value) && 'text-muted-foreground',
            )}
          >
            {triggerLabel}
          </span>
          <ChevronDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
      >
        {/* Post-approval nit N1: when a caller drives a server-searched
            options set (`onQueryChange`), cmdk's own fuzzy filter must NOT
            ALSO re-filter the page it just fetched - see multi-select.tsx's
            matching comment for the full reasoning. */}
        <Command shouldFilter={!onQueryChange}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(v) => {
              setQuery(v);
              typedRef.current = v;
              onQueryChange?.(v);
            }}
          />
          <CommandList>
            {!showCustom && <CommandEmpty>{emptyText}</CommandEmpty>}
            {showCustom && (
              <CommandGroup>
                <CommandItem
                  key="__custom__"
                  value={trimmed}
                  onSelect={() => {
                    onChange(trimmed);
                    setOpen(false);
                  }}
                >
                  <Check className="size-4 opacity-0" />
                  {customLabel ? customLabel(trimmed) : `Use "${trimmed}"`}
                </CommandItem>
              </CommandGroup>
            )}
            {(
              groups ?? [
                { label: undefined as string | undefined, options: flat },
              ]
            ).map((group, groupIndex) => (
              <CommandGroup
                key={group.label ?? groupIndex}
                heading={group.label}
              >
                {group.options.map((option) => (
                  <CommandItem
                    key={option.value}
                    // Unique cmdk value (label alone collides for same-named
                    // options - e.g. two "Archive" edges; code-review fix).
                    // Search still matches the label prefix of the string.
                    value={`${option.label} ${option.value}`}
                    onSelect={() => {
                      onChange(option.value);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        'size-4',
                        option.value === value ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                    {option.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
