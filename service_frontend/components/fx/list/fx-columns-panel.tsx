'use client';

/**
 * The Columns panel (playbook 0.71.0 "Lists", "Columns" and "Drag to
 * reorder"), opened by the Columns icon button beside the view toggle.
 *
 * - Titled "Smart view columns" or "Table view columns" for the view that is
 *   selected; switching the view with the panel open swaps it.
 * - "Apply the same to Table view" (or Smart view) copies this view's columns
 *   to the other and keeps them the same while ticked.
 * - One row per column (top is left) with a switch to show or hide it, and
 *   Reset. At least one column always stays shown. Tick boxes and row actions
 *   are not listed.
 * - Drag a row to change the order: with a mouse from anywhere on it once it
 *   has moved 4px, on touch after a short press (so a quick swipe still
 *   scrolls the list), and from the keyboard with the grip (Space picks up,
 *   arrows move, Space drops, Esc cancels; the grip is `aria-pressed` while
 *   held and described by those keys), each step announced.
 */
import { useId, useState } from 'react';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
} from '@dnd-kit/core';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { FxIconActionButton } from '@/components/fx/actions/icon-action';

export interface FxPanelColumn {
  id: string;
  label: string;
}

export interface FxColumnsPanelProps {
  view: 'smart' | 'table';
  /** Data columns in their current order (top is left). */
  columns: FxPanelColumn[];
  hidden: string[];
  same: boolean;
  /** Setting "Choose and order columns": off hides the order controls. */
  onSame: (same: boolean) => void;
  onChange: (order: string[], hidden: string[]) => void;
  onReset: () => void;
}

const VIEW_NAME = { smart: 'Smart view', table: 'Table view' } as const;

export function FxColumnsPanel({
  view,
  columns,
  hidden,
  same,
  onSame,
  onChange,
  onReset,
}: FxColumnsPanelProps) {
  const [open, setOpen] = useState(false);
  const title = `${VIEW_NAME[view]} columns`;
  const other = VIEW_NAME[view === 'smart' ? 'table' : 'smart'];
  const shownCount = columns.filter((c) => !hidden.includes(c.id)).length;
  const ids = columns.map((c) => c.id);
  const nameOf = (id: string | number) => columns.find((c) => c.id === String(id))?.label ?? String(id);
  const positionOf = (id: string | number) => ids.indexOf(String(id)) + 1;

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const announcements: Announcements = {
    onDragStart: ({ active }) => `${nameOf(active.id)} picked up, position ${positionOf(active.id)} of ${ids.length}`,
    onDragOver: ({ active, over }) =>
      over ? `${nameOf(active.id)}, position ${positionOf(over.id)} of ${ids.length}` : `${nameOf(active.id)} is outside the list`,
    onDragEnd: ({ active, over }) =>
      over
        ? `${nameOf(active.id)} moved to column ${positionOf(over.id)} of ${ids.length}`
        : `${nameOf(active.id)} put back`,
    onDragCancel: ({ active }) => `${nameOf(active.id)} put back`,
  };

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onChange(arrayMove(ids, from, to), hidden);
  };

  const toggle = (id: string, show: boolean) => {
    const next = show ? hidden.filter((h) => h !== id) : [...hidden, id];
    onChange(ids, next);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <FxTooltip label="Columns">
        <PopoverTrigger asChild>
          <FxIconActionButton label="Columns" icon="columns" />
        </PopoverTrigger>
      </FxTooltip>
      <PopoverContent
        align="end"
        aria-label={title}
        className="fx-see-through flex max-h-[70dvh] w-72 flex-col overflow-hidden rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface)/50 p-0 text-(--fx-ink)"
      >
        <div className="flex flex-col gap-2 border-b border-(--fx-line) p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold">{title}</span>
            <Button type="button" variant="fx-text" size="sm" onClick={onReset}>
              Reset
            </Button>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-(--fx-ink-2)">
            <Checkbox checked={same} onCheckedChange={(c) => onSame(Boolean(c))} />
            Apply the same to {other}
          </label>
        </div>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements,
            screenReaderInstructions: {
              draggable: 'Press Space to pick up, the arrow keys to move, Space to drop, Escape to cancel.',
            },
          }}
        >
          <SortableContext items={ids} strategy={verticalListSortingStrategy}>
            <ul className="flex flex-col overflow-y-auto p-1" data-fx-columns-list="">
              {columns.map((c) => {
                const shown = !hidden.includes(c.id);
                return (
                  <PanelRow
                    key={c.id}
                    column={c}
                    shown={shown}
                    lastShown={shown && shownCount <= 1}
                    onToggle={(show) => toggle(c.id, show)}
                  />
                );
              })}
            </ul>
          </SortableContext>
        </DndContext>
      </PopoverContent>
    </Popover>
  );
}

function PanelRow({
  column,
  shown,
  lastShown,
  onToggle,
}: {
  column: FxPanelColumn;
  shown: boolean;
  lastShown: boolean;
  onToggle: (show: boolean) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: column.id });
  const switchId = useId();
  return (
    <li
      ref={setNodeRef}
      data-dragging={isDragging || undefined}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      // Mouse: the whole row drags (after 4px); touch and keyboard use the grip.
      {...listeners}
      className={cn(
        'flex items-center gap-2 rounded-(--fx-r-m) px-1 py-1 text-sm',
        'data-[dragging=true]:relative data-[dragging=true]:z-(--fx-z-pop) data-[dragging=true]:rotate-[0.6deg] data-[dragging=true]:scale-[1.02] data-[dragging=true]:bg-(--fx-surface) data-[dragging=true]:shadow-[0_8px_20px_var(--fx-shade)]',
      )}
    >
      <Button
        ref={setActivatorNodeRef}
        type="button"
        variant="ghost"
        mode="icon"
        size="sm"
        aria-label={`Reorder ${column.label}`}
        className="size-7 cursor-grab touch-none text-(--fx-ink-3)"
        {...attributes}
      >
        <GripVertical className="size-4" />
      </Button>
      <label htmlFor={switchId} className="min-w-0 flex-1 cursor-pointer break-words">
        {column.label}
      </label>
      <Switch
        id={switchId}
        size="sm"
        checked={shown}
        disabled={lastShown}
        aria-label={`Show ${column.label}`}
        onCheckedChange={(c) => onToggle(Boolean(c))}
        onPointerDown={(e) => e.stopPropagation()}
      />
    </li>
  );
}
