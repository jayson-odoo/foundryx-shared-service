'use client';

/**
 * Form-builder palette (plan sprint-3/01 D7) - collapsed-by-default category
 * sections with counts + a search box (house node-palette pattern). Each entry
 * is BOTH click-to-add (appends to the selected/last section - the E2E path,
 * dnd-kit drags aren't drivable via scripted browser automation) AND dnd-kit
 * draggable onto a section/gap in the canvas. Not asserted in jsdom; the
 * drag-onto-canvas behaviour needs a recorded agent-browser check in any
 * slice that touches it. No instructional copy (foolproof-UI mandate).
 */
import { useMemo, useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';
import type { FormFieldType } from '@/types/forms';
import { FIELD_ICONS, PALETTE_CATEGORIES, fieldMeta } from './field-catalog';

function PaletteItem({
  type,
  disabled,
  onAdd,
}: {
  type: FormFieldType;
  disabled: boolean;
  onAdd: (type: FormFieldType) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `form-palette-${type}`,
    data: { source: 'palette', fieldType: type },
    disabled,
  });
  const meta = fieldMeta(type);
  const Icon = FIELD_ICONS[type];
  return (
    <button
      ref={setNodeRef}
      type="button"
      data-testid={`palette-${type}`}
      onClick={() => !disabled && onAdd(type)}
      className={`flex w-full items-center gap-2 rounded-md border border-input bg-background px-2.5 py-1.5 text-left text-xs text-foreground transition-colors ${
        disabled
          ? 'cursor-not-allowed opacity-50'
          : 'cursor-grab hover:border-primary hover:text-primary'
      } ${isDragging ? 'opacity-40' : ''}`}
      {...listeners}
      {...attributes}
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate">{meta.label}</span>
    </button>
  );
}

export interface PaletteProps {
  disabled: boolean;
  onAdd: (type: FormFieldType) => void;
}

export function Palette({ disabled, onAdd }: PaletteProps) {
  const [query, setQuery] = useState('');
  // Collapsed by default; search auto-expands matching categories.
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  const term = query.trim().toLowerCase();
  const categories = useMemo(() => {
    if (!term) return PALETTE_CATEGORIES.map((c) => ({ ...c, types: c.types }));
    return PALETTE_CATEGORIES.map((category) => ({
      ...category,
      types: category.types.filter((type) =>
        fieldMeta(type).label.toLowerCase().includes(term),
      ),
    })).filter((category) => category.types.length > 0);
  }, [term]);

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-2" data-testid="form-palette">
      <div className="relative">
        <Search className="pointer-events-none absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search fields"
          aria-label="Search fields"
          className="h-8 ps-8 text-xs"
        />
      </div>
      <div className="flex flex-col gap-1">
        {categories.map((category) => {
          const open = term ? true : openIds.has(category.id);
          return (
            <div key={category.id} className="rounded-md">
              <button
                type="button"
                data-testid={`palette-category-${category.id}`}
                onClick={() => toggle(category.id)}
                className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
              >
                {open ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                <span className="flex-1 text-start">{category.label}</span>
                <span className="text-[10px] font-normal">{category.types.length}</span>
              </button>
              {open && (
                <div className="flex flex-col gap-1 px-1 pb-1.5 pt-0.5">
                  {category.types.map((type) => (
                    <PaletteItem
                      key={type}
                      type={type}
                      disabled={disabled}
                      onAdd={onAdd}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {categories.length === 0 && (
          <p className="px-1.5 py-2 text-xs text-muted-foreground">No matching fields.</p>
        )}
      </div>
    </div>
  );
}
