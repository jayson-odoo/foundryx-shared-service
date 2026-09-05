'use client';

import { useDndContext, useDraggable, useDroppable } from '@dnd-kit/core';
import { ChevronDown, ChevronUp, GripVertical, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import type { BrandRenderValues } from '@/lib/template-render';
import {
  SECTION_LAYOUT_COLUMNS,
  type TemplateBlock,
  type TemplateColumn,
  type TemplateDocument,
  type TemplateListFact,
  type TemplateSection,
} from '@/types/templates';
import { BlockView, ConditionIndicator } from './block-view';
import type { EditorSurface } from './email-editor';

export type EditorSelection =
  | { kind: 'block'; id: string }
  | { kind: 'section'; id: string }
  | null;

export interface CanvasProps {
  doc: TemplateDocument;
  editing: boolean;
  /** Editor surface - drives nothing visual here, carried for parity. */
  surface?: EditorSurface;
  /** Lock add/reorder/delete of sections+blocks (content-only edit). */
  structureLocked?: boolean;
  selection: EditorSelection;
  brand: BrandRenderValues;
  /** List facts (document surface) - sample rows for table/repeater previews. */
  listFacts?: TemplateListFact[];
  onSelect: (selection: EditorSelection) => void;
  onInlineChange: (blockId: string, patch: Partial<TemplateBlock>) => void;
  onAddSection: (index: number) => void;
  onMoveSection: (sectionId: string, direction: -1 | 1) => void;
  onRemoveSection: (sectionId: string) => void;
}

/**
 * Droppable insertion gap - drop target before block `index` in a column.
 * Invisible 8px strip at rest; while a drag is active it expands into a
 * visible dashed slot (2px targets were impossible to hit - UX iteration).
 */
function DropGap({
  sectionId,
  columnId,
  index,
  disabled,
  dragActive,
  grow,
}: {
  sectionId: string;
  columnId: string;
  index: number;
  disabled: boolean;
  dragActive: boolean;
  /** Empty-column variant: fill the column so the whole area is a target. */
  grow?: boolean;
}) {
  // Id includes the SECTION: imported/legacy docs may reuse column ids
  // across sections (the seeded system templates did) - duplicate droppable
  // ids make dnd-kit silently drop all but one zone (the "can't drop here"
  // bug).
  const { isOver, setNodeRef } = useDroppable({
    id: `gap-${sectionId}-${columnId}-${index}`,
    data: { target: 'gap', sectionId, columnId, index },
    disabled,
  });

  if (grow) {
    return (
      <div
        ref={setNodeRef}
        data-testid={`drop-gap-${columnId}-${index}`}
        className={`flex items-center justify-center rounded-md border border-dashed px-3 py-6 text-xs transition-colors ${
          isOver
            ? 'border-primary bg-primary/10 text-primary'
            : dragActive
              ? 'border-primary/50 bg-primary/5 text-primary/80'
              : 'border-input text-muted-foreground'
        }`}
      >
        {disabled ? 'Empty column' : 'Drop a block here'}
      </div>
    );
  }

  return (
    <div
      ref={setNodeRef}
      data-testid={`drop-gap-${columnId}-${index}`}
      className={`rounded transition-[height,margin,background-color,border-color,border-width] ${
        isOver
          ? 'my-1 h-9 border border-dashed border-primary bg-primary/10'
          : dragActive
            ? 'my-1 h-6 border border-dashed border-primary/40 bg-primary/5'
            : '-my-1 h-2'
      }`}
    />
  );
}

function CanvasBlock({
  block,
  index,
  sectionId,
  columnId,
  editing,
  structureLocked,
  selected,
  brand,
  listFacts,
  onSelect,
  onInlineChange,
}: {
  block: TemplateBlock;
  index: number;
  sectionId: string;
  columnId: string;
  editing: boolean;
  structureLocked: boolean;
  selected: boolean;
  brand: BrandRenderValues;
  listFacts: TemplateListFact[];
  onSelect: (selection: EditorSelection) => void;
  onInlineChange: (blockId: string, patch: Partial<TemplateBlock>) => void;
}) {
  const canStructure = editing && !structureLocked;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: block.id,
    data: { source: 'canvas', blockId: block.id, sectionId, columnId },
    disabled: !canStructure,
  });
  // The block itself is a drop target - dropping ON a block inserts AFTER it
  // (hunting for the thin gap between blocks was unusable - UX iteration).
  const drop = useDroppable({
    id: `after-${block.id}`,
    data: { target: 'gap', sectionId, columnId, index: index + 1 },
    disabled: !canStructure,
  });

  return (
    <div
      ref={(node) => {
        setNodeRef(node);
        drop.setNodeRef(node);
      }}
      data-testid={`canvas-block-${block.id}`}
      // Selection = FLUSH square outline (no offset/rounding) - offset
      // dashed boxes collided with neighbouring blocks; a rounded ring read
      // as an input field (two UX iterations). Never part of the email.
      className={`group/block relative transition-[outline] ${isDragging ? 'opacity-40' : ''} ${
        selected
          ? 'outline outline-2 outline-primary'
          : editing
            ? 'hover:outline hover:outline-1 hover:outline-primary/40'
            : ''
      }`}
      onClick={(e) => {
        e.stopPropagation();
        if (editing) onSelect({ kind: 'block', id: block.id });
      }}
    >
      <ConditionIndicator visible={Boolean(block.conditionsJson)} />
      {/* Insertion line: dropping here lands AFTER this block. */}
      {drop.isOver && (
        <div className="absolute -bottom-1 start-0 end-0 z-20 h-1 rounded bg-primary" />
      )}
      {canStructure && (
        /* Drag handle in the LEFT GUTTER. The wrapper anchors FLUSH to the
           block edge (end-full) and the padding bridges the visual gap -
           the pointer never crosses a dead zone, so :hover survives the
           travel (third round of the disappearing-controls bug). */
        <div
          className={`absolute end-full top-1/2 z-20 -translate-y-1/2 pe-1.5 ${
            selected ? 'block' : 'hidden group-hover/block:block'
          }`}
        >
          <button
            type="button"
            aria-label="Drag block"
            data-testid={`block-handle-${block.id}`}
            className={cn(PRESSED_CLASS, 'cursor-grab rounded border border-input bg-background p-1 text-muted-foreground shadow-sm hover:text-foreground active:cursor-grabbing')}
            {...listeners}
            {...attributes}
          >
            <GripVertical className="size-3.5" />
          </button>
        </div>
      )}
      <BlockView
        block={block}
        editing={editing}
        brand={brand}
        listFacts={listFacts}
        onInlineChange={(patch) => onInlineChange(block.id, patch)}
      />
    </div>
  );
}

function CanvasColumn({
  column,
  section,
  widthPct,
  editing,
  structureLocked,
  selection,
  brand,
  listFacts,
  dragActive,
  onSelect,
  onInlineChange,
}: {
  column: TemplateColumn;
  section: TemplateSection;
  widthPct: number;
  editing: boolean;
  structureLocked: boolean;
  selection: EditorSelection;
  brand: BrandRenderValues;
  listFacts: TemplateListFact[];
  dragActive: boolean;
  onSelect: (selection: EditorSelection) => void;
  onInlineChange: (blockId: string, patch: Partial<TemplateBlock>) => void;
}) {
  const empty = column.blocks.length === 0;
  const gapDisabled = !editing || structureLocked;

  if (empty) {
    // The whole empty column is ONE big drop zone - a 2px gap above a
    // non-droppable placeholder was unhittable.
    return (
      <div className="min-w-0" style={{ width: `${widthPct}%` }}>
        <DropGap
          sectionId={section.id}
          columnId={column.id}
          index={0}
          disabled={gapDisabled}
          dragActive={dragActive}
          grow
        />
      </div>
    );
  }

  return (
    <div className="min-w-0" style={{ width: `${widthPct}%` }}>
      <DropGap
        sectionId={section.id}
        columnId={column.id}
        index={0}
        disabled={gapDisabled}
        dragActive={dragActive}
      />
      {column.blocks.map((block, i) => (
        <div key={block.id}>
          <CanvasBlock
            block={block}
            index={i}
            sectionId={section.id}
            columnId={column.id}
            editing={editing}
            structureLocked={structureLocked}
            selected={selection?.kind === 'block' && selection.id === block.id}
            brand={brand}
            listFacts={listFacts}
            onSelect={onSelect}
            onInlineChange={onInlineChange}
          />
          <DropGap
            sectionId={section.id}
            columnId={column.id}
            index={i + 1}
            disabled={gapDisabled}
            dragActive={dragActive}
          />
        </div>
      ))}
    </div>
  );
}

function AddSectionRow({ index, onAdd, visible }: { index: number; onAdd: (index: number) => void; visible: boolean }) {
  if (!visible) return null;
  return (
    <div className="flex justify-center py-1 opacity-0 transition-opacity hover:opacity-100">
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid={`add-section-${index}`}
        onClick={() => onAdd(index)}
      >
        <Plus className="size-3.5" /> Add section
      </Button>
    </div>
  );
}

export function Canvas({
  doc,
  editing,
  structureLocked = false,
  selection,
  brand,
  listFacts = [],
  onSelect,
  onInlineChange,
  onAddSection,
  onMoveSection,
  onRemoveSection,
}: CanvasProps) {
  // Expands the drop targets the moment ANY drag starts.
  const { active } = useDndContext();
  const canStructure = editing && !structureLocked;
  const dragActive = canStructure && active !== null;

  return (
    <div
      data-testid="email-canvas"
      className="mx-auto w-full max-w-[600px] bg-white shadow-sm"
      onClick={() => onSelect(null)}
    >
      <AddSectionRow index={0} onAdd={onAddSection} visible={canStructure} />
      {doc.sections.map((section, sIndex) => {
        const ratios = SECTION_LAYOUT_COLUMNS[section.layout];
        const selected = selection?.kind === 'section' && selection.id === section.id;
        return (
          <div key={section.id}>
            <div
              data-testid={`canvas-section-${section.id}`}
              className={`group/section relative ${selected ? 'outline outline-2 outline-primary/60' : editing ? 'hover:outline hover:outline-1 hover:outline-primary/25' : ''}`}
              style={{ backgroundColor: section.background ?? undefined }}
              onClick={(e) => {
                e.stopPropagation();
                if (editing) onSelect({ kind: 'section', id: section.id });
              }}
            >
              <ConditionIndicator visible={Boolean(section.conditionsJson)} />
              {canStructure && (
                /* Toolbar in the RIGHT GUTTER. Wrapper anchors FLUSH to the
                   section edge (start-full) with padding bridging the gap so
                   :hover survives the pointer travel - an offset gutter left
                   a dead zone that hid the buttons mid-travel. */
                <div
                  className={`absolute start-full top-1 z-20 ps-1.5 ${
                    selected ? 'block' : 'hidden group-hover/section:block'
                  }`}
                >
                <div className="flex flex-col gap-0.5 rounded-md border border-input bg-background p-0.5 shadow-sm">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6"
                    aria-label="Move section up"
                    disabled={sIndex === 0}
                    onClick={(e) => {
                      e.stopPropagation();
                      onMoveSection(section.id, -1);
                    }}
                  >
                    <ChevronUp className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6"
                    aria-label="Move section down"
                    disabled={sIndex === doc.sections.length - 1}
                    onClick={(e) => {
                      e.stopPropagation();
                      onMoveSection(section.id, 1);
                    }}
                  >
                    <ChevronDown className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6 text-destructive"
                    aria-label="Delete section"
                    data-testid={`delete-section-${section.id}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveSection(section.id);
                    }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
                </div>
              )}
              <div
                className="flex gap-1"
                style={{
                  padding: `${section.padding.top}px ${section.padding.right}px ${section.padding.bottom}px ${section.padding.left}px`,
                }}
              >
                {section.columns.map((column, i) => (
                  <CanvasColumn
                    key={column.id}
                    column={column}
                    section={section}
                    widthPct={ratios[i]}
                    editing={editing}
                    structureLocked={structureLocked}
                    selection={selection}
                    brand={brand}
                    listFacts={listFacts}
                    dragActive={dragActive}
                    onSelect={onSelect}
                    onInlineChange={onInlineChange}
                  />
                ))}
              </div>
            </div>
            <AddSectionRow index={sIndex + 1} onAdd={onAddSection} visible={canStructure} />
          </div>
        );
      })}
    </div>
  );
}
