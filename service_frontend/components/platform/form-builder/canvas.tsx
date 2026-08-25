'use client';

/**
 * Form-builder canvas (plan sprint-3/01 D6) - a VERTICAL page/section/field
 * list editor (NOT a node graph). Pages are cards; each holds titled sections;
 * sections hold field rows. Click selects a page/section/field (visual ring);
 * dnd-kit sortable reorders fields within/between sections; hover row actions
 * (duplicate/delete field, section add-field/delete, page delete) appear in
 * edit mode only. Read-only when !editing: no actions, no inputs, just the
 * approximation. No instructional copy (foolproof-UI mandate).
 */
import { useDroppable } from '@dnd-kit/core';
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  Copy,
  GitBranch,
  GripVertical,
  Plus,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { FormDocument, FormField, FormPage, FormSection } from '@/types/forms';
import { FieldPreview } from './field-preview';
import type { BuilderSelection } from './selection';

interface CanvasCallbacks {
  onSelect: (selection: BuilderSelection) => void;
  onPageTitleChange: (pageId: string, title: string) => void;
  onSectionTitleChange: (sectionId: string, title: string) => void;
  onDuplicateField: (fieldId: string) => void;
  onRemoveField: (fieldId: string) => void;
  onAddFieldToSection: (sectionId: string) => void;
  onRemoveSection: (sectionId: string) => void;
  onAddSection: (pageId: string) => void;
  onRemovePage: (pageId: string) => void;
  onAddPage: () => void;
}

export interface CanvasProps extends CanvasCallbacks {
  doc: FormDocument;
  editing: boolean;
  selection: BuilderSelection;
}

// ---- field row (sortable) ----

function FieldRow({
  field,
  editing,
  selected,
  onSelect,
  onDuplicateField,
  onRemoveField,
}: {
  field: FormField;
  editing: boolean;
  selected: boolean;
} & Pick<CanvasCallbacks, 'onSelect' | 'onDuplicateField' | 'onRemoveField'>) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: field.id,
    data: { type: 'field', fieldId: field.id },
    disabled: !editing,
  });
  const style = { transform: CSS.Translate.toString(transform), transition };
  const hasCondition = Boolean(field.conditionsJson);

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`field-row-${field.id}`}
      data-field-type={field.type}
      onClick={(e) => {
        e.stopPropagation();
        onSelect({ kind: 'field', id: field.id });
      }}
      className={cn(
        'group/field relative flex items-start gap-1.5 rounded-md border bg-background p-2 transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-input hover:border-primary/40',
        isDragging && 'opacity-50',
      )}
    >
      {editing && (
        <button
          type="button"
          aria-label="Drag to reorder"
          className="mt-0.5 cursor-grab text-muted-foreground/60 hover:text-foreground"
          {...listeners}
          {...attributes}
        >
          <GripVertical className="size-4" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <FieldPreview field={field} />
      </div>
      {hasCondition && (
        <GitBranch
          className="mt-0.5 size-3.5 shrink-0 text-primary"
          aria-label="Has visibility condition"
        />
      )}
      {editing && (
        <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/field:opacity-100">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6"
            aria-label="Duplicate field"
            data-testid={`field-duplicate-${field.id}`}
            onClick={(e) => {
              e.stopPropagation();
              onDuplicateField(field.id);
            }}
          >
            <Copy className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 text-destructive"
            aria-label="Delete field"
            data-testid={`field-delete-${field.id}`}
            onClick={(e) => {
              e.stopPropagation();
              onRemoveField(field.id);
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ---- empty-section drop zone (palette drop target) ----

function EmptyDrop({ sectionId, editing }: { sectionId: string; editing: boolean }) {
  const { isOver, setNodeRef } = useDroppable({
    id: `section-empty-${sectionId}`,
    data: { type: 'section-empty', sectionId },
    disabled: !editing,
  });
  return (
    <div
      ref={setNodeRef}
      data-testid={`section-empty-${sectionId}`}
      className={cn(
        'flex h-14 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground',
        isOver ? 'border-primary bg-primary/5 text-primary' : 'border-input',
      )}
    >
      No fields yet
    </div>
  );
}

// ---- section (sortable within its page) ----

function SectionCard({
  section,
  pageId,
  editing,
  selection,
  ...cb
}: {
  section: FormSection;
  pageId: string;
  editing: boolean;
  selection: BuilderSelection;
} & CanvasCallbacks) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: section.id,
    data: { type: 'section', sectionId: section.id, pageId },
    disabled: !editing,
  });
  const style = { transform: CSS.Translate.toString(transform), transition };
  const selected = selection?.kind === 'section' && selection.id === section.id;
  const hasCondition = Boolean(section.conditionsJson);

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`section-card-${section.id}`}
      onClick={(e) => {
        e.stopPropagation();
        cb.onSelect({ kind: 'section', id: section.id });
      }}
      className={cn(
        'group/section rounded-lg border bg-muted/30 p-3 transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-input',
        isDragging && 'opacity-50',
      )}
    >
      <div className="mb-2 flex items-center gap-1.5">
        {editing && (
          <button
            type="button"
            aria-label="Drag section"
            className="cursor-grab text-muted-foreground/60 hover:text-foreground"
            {...listeners}
            {...attributes}
          >
            <GripVertical className="size-4" />
          </button>
        )}
        {editing ? (
          <Input
            value={section.title ?? ''}
            placeholder="Section title"
            aria-label="Section title"
            data-testid={`section-title-${section.id}`}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => cb.onSectionTitleChange(section.id, e.target.value)}
            className="h-7 flex-1 border-transparent bg-transparent px-1 text-sm font-semibold focus-visible:border-input focus-visible:bg-background"
          />
        ) : (
          <span className="flex-1 truncate text-sm font-semibold">
            {section.title || 'Untitled section'}
          </span>
        )}
        {hasCondition && <GitBranch className="size-3.5 text-primary" aria-label="Conditional section" />}
        {editing && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 text-destructive opacity-0 transition-opacity group-hover/section:opacity-100"
            aria-label="Delete section"
            data-testid={`section-delete-${section.id}`}
            onClick={(e) => {
              e.stopPropagation();
              cb.onRemoveSection(section.id);
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>

      {section.fields.length === 0 ? (
        <EmptyDrop sectionId={section.id} editing={editing} />
      ) : (
        <SortableContext items={section.fields.map((f) => f.id)} strategy={verticalListSortingStrategy}>
          <div className={cn('grid gap-2', section.twoColumn ? 'sm:grid-cols-2' : 'grid-cols-1')}>
            {section.fields.map((field) => (
              <FieldRow
                key={field.id}
                field={field}
                editing={editing}
                selected={selection?.kind === 'field' && selection.id === field.id}
                onSelect={cb.onSelect}
                onDuplicateField={cb.onDuplicateField}
                onRemoveField={cb.onRemoveField}
              />
            ))}
          </div>
        </SortableContext>
      )}

      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2 h-7 text-xs"
          data-testid={`section-add-field-${section.id}`}
          onClick={(e) => {
            e.stopPropagation();
            cb.onAddFieldToSection(section.id);
          }}
        >
          <Plus className="size-3.5" /> Add field
        </Button>
      )}
    </div>
  );
}

// ---- page card (sortable) ----

function PageCard({
  page,
  index,
  editing,
  selection,
  ...cb
}: {
  page: FormPage;
  index: number;
  editing: boolean;
  selection: BuilderSelection;
} & CanvasCallbacks) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: page.id,
    data: { type: 'page', pageId: page.id },
    disabled: !editing,
  });
  const style = { transform: CSS.Translate.toString(transform), transition };
  const selected = selection?.kind === 'page' && selection.id === page.id;

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`page-card-${page.id}`}
      onClick={(e) => {
        e.stopPropagation();
        cb.onSelect({ kind: 'page', id: page.id });
      }}
      className={cn(
        'group/page rounded-xl border bg-background p-4 transition-colors',
        selected ? 'border-primary ring-1 ring-primary' : 'border-input',
        isDragging && 'opacity-50',
      )}
    >
      <div className="mb-3 flex items-center gap-1.5">
        {editing && (
          <button
            type="button"
            aria-label="Drag page"
            className="cursor-grab text-muted-foreground/60 hover:text-foreground"
            {...listeners}
            {...attributes}
          >
            <GripVertical className="size-4" />
          </button>
        )}
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">
          Page {index + 1}
        </span>
        {editing ? (
          <Input
            value={page.title ?? ''}
            placeholder="Page title"
            aria-label="Page title"
            data-testid={`page-title-${page.id}`}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => cb.onPageTitleChange(page.id, e.target.value)}
            className="h-7 flex-1 border-transparent bg-transparent px-1 text-sm font-semibold focus-visible:border-input focus-visible:bg-background"
          />
        ) : (
          <span className="flex-1 truncate text-sm font-semibold">{page.title || 'Untitled page'}</span>
        )}
        {editing && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 text-destructive opacity-0 transition-opacity group-hover/page:opacity-100"
            aria-label="Delete page"
            data-testid={`page-delete-${page.id}`}
            onClick={(e) => {
              e.stopPropagation();
              cb.onRemovePage(page.id);
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>

      <SortableContext items={page.sections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-3">
          {page.sections.map((section) => (
            <SectionCard
              key={section.id}
              section={section}
              pageId={page.id}
              editing={editing}
              selection={selection}
              {...cb}
            />
          ))}
        </div>
      </SortableContext>

      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3 h-7 text-xs"
          data-testid={`page-add-section-${page.id}`}
          onClick={(e) => {
            e.stopPropagation();
            cb.onAddSection(page.id);
          }}
        >
          <Plus className="size-3.5" /> Add section
        </Button>
      )}
    </div>
  );
}

export function Canvas({ doc, editing, selection, ...cb }: CanvasProps) {
  return (
    // Click the empty canvas background (not a card) → deselect, so a selected
    // page/section/field's highlight clears (the selectable cards stopPropagation).
    <div
      className="flex min-h-full flex-col gap-4"
      data-testid="form-canvas"
      onClick={(e) => {
        if (e.target === e.currentTarget) cb.onSelect(null);
      }}
    >
      <SortableContext items={doc.pages.map((p) => p.id)} strategy={verticalListSortingStrategy}>
        {doc.pages.map((page, index) => (
          <PageCard
            key={page.id}
            page={page}
            index={index}
            editing={editing}
            selection={selection}
            {...cb}
          />
        ))}
      </SortableContext>
      {editing && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          data-testid="form-add-page"
          onClick={cb.onAddPage}
        >
          <Plus className="size-4" /> Add page
        </Button>
      )}
    </div>
  );
}
