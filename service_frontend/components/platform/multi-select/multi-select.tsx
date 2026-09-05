'use client';

import { useEffect, useState } from 'react';
import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
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

export interface MultiSelectOption {
  label: string;
  value: string;
}

export interface MultiSelectProps {
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  size?: 'sm' | 'md';
  className?: string;
  disabled?: boolean;
}

/**
 * Searchable dropdown multi-select with selected values shown as removable
 * pills. System-wide control for any "pick many from a growing list" field
 * (roles now; reused by future entities + the filter builder). Plan 02 review.
 */
export function MultiSelect({
  options,
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches.',
  size = 'md',
  className,
  disabled = false,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // Clear the typed search whenever the popover closes (same reasoning as
  // SearchSelect: a programmatic close via a select doesn't fire
  // onOpenChange, so the next open's text would otherwise append to stale
  // query text).
  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const selected = options.filter((o) => value.includes(o.value));
  const toggle = (v: string) =>
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  const allSelected = options.length > 0 && value.length === options.length;

  return (
    // modal: inside a Sheet/Dialog the scroll lock otherwise swallows wheel
    // events - the option list wouldn't scroll (sprint-2/02 iteration).
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size={size === 'sm' ? 'sm' : 'md'}
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            'h-auto min-h-9 w-full justify-between gap-1 py-1.5',
            size === 'sm' && 'min-h-8',
            className,
          )}
        >
          <span className="flex flex-1 flex-wrap items-center gap-1">
            {selected.length === 0 ? (
              <span className="text-muted-foreground">{placeholder}</span>
            ) : (
              selected.map((o) => (
                <Badge
                  key={o.value}
                  variant="secondary"
                  appearance="light"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggle(o.value);
                  }}
                >
                  {o.label}
                  <X className="ms-0.5 size-3 opacity-60 hover:opacity-100" />
                </Badge>
              ))
            )}
          </span>
          <ChevronDown className="size-4 shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[--radix-popover-trigger-width] p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} value={query} onValueChange={setQuery} />
          <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
            <span className="text-xs text-muted-foreground">
              {value.length} selected
            </span>
            <button
              type="button"
              className={cn(PRESSED_CLASS, 'text-xs font-medium text-primary hover:underline')}
              onClick={() =>
                onChange(allSelected ? [] : options.map((o) => o.value))
              }
            >
              {allSelected ? 'Clear all' : 'Select all'}
            </button>
          </div>
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {options.map((o) => {
                const on = value.includes(o.value);
                return (
                  <CommandItem
                    key={o.value}
                    value={o.label}
                    onSelect={() => toggle(o.value)}
                  >
                    <span
                      className={cn(
                        'flex size-4 items-center justify-center rounded-sm border border-border',
                        on &&
                          'bg-primary border-primary text-primary-foreground',
                      )}
                    >
                      {on && <Check className="size-3" />}
                    </span>
                    {o.label}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
