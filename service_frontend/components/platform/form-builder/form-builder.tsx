'use client';

/**
 * FormBuilder (plan sprint-3/01 D6/D7/D18) - the drag-drop form designer. The
 * 5th core engine's authoring surface; mirrors the EmailEditor composition
 * skeleton (Palette · Canvas · SettingsPanel, dnd-kit, the container owns
 * selection + undo/redo via the shared `useHistory`). Editor-agnostic:
 * `FormDocument` in/out is the only contract (types/forms.ts). Every mutation
 * is gated by the global `editing` toggle (ResourceForm Edit) - read-only
 * render otherwise. Pure component (no fetch/services). No instructional copy
 * (foolproof-UI mandate) - labels + state warnings only.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { Redo2, Undo2 } from 'lucide-react';
import { useHistory } from '@/components/platform/flow-canvas/use-history';
import { Button } from '@/components/ui/button';
import type {
  FormChoiceItem,
  FormDocument,
  FormField,
  FormFieldType,
  FormSection,
  FormSubField,
  FormSubFieldType,
} from '@/types/forms';
import { Canvas } from './canvas';
import { Palette } from './palette';
import { SettingsPanel } from './settings-panel';
import { fieldMeta } from './field-catalog';
import type { BuilderSelection } from './selection';
import {
  addOption,
  addPage,
  addSection,
  addSubField,
  changeFieldType,
  duplicateField,
  insertField,
  lastSectionId,
  moveField,
  moveOption,
  movePage,
  moveSection,
  moveSubField,
  removeField,
  removeOption,
  removePage,
  removeSection,
  removeSubField,
  sectionOf,
  updateField,
  updateOption,
  updatePage,
  updateSection,
  updateSubField,
} from './doc-ops';

/** Pointer hit first; rect overlap as a fallback so near-misses land. */
const collisionDetection: CollisionDetection = (args) => {
  const pointer = pointerWithin(args);
  return pointer.length ? pointer : rectIntersection(args);
};

export interface FormBuilderProps {
  doc: FormDocument;
  onChange: (doc: FormDocument) => void;
  /** Global Edit toggle (ResourceForm) gates EVERY mutation - read-only render otherwise. */
  editing: boolean;
}

type PaletteDragData = { source: 'palette'; fieldType: FormFieldType };

export function FormBuilder({ doc, onChange, editing }: FormBuilderProps) {
  const [selection, setSelection] = useState<BuilderSelection>(null);
  const [dragLabel, setDragLabel] = useState<string | null>(null);
  const history = useHistory(doc, onChange);
  const { set: emit, undo, redo, canUndo, canRedo } = history;

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  // ⌘Z / ⇧⌘Z / Ctrl+Y - skip when focus is in any interactive control so the
  // native text-undo and dropdown navigation keep working (house guard).
  useEffect(() => {
    if (!editing) return;
    const handler = (e: KeyboardEvent) => {
      const isZ = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z';
      const isY = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'y';
      if (!isZ && !isY) return;
      const target = e.target as HTMLElement | null;
      if (
        target?.closest(
          'input, textarea, select, [contenteditable="true"], [role="combobox"], [role="textbox"]',
        )
      ) {
        return;
      }
      e.preventDefault();
      if (isY || e.shiftKey) redo();
      else undo();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, undo, redo]);

  // ---- click-to-add (E2E path; appends to selected/last section) ----
  const resolveTargetSection = useCallback((): string | null => {
    if (selection?.kind === 'section') return selection.id;
    if (selection?.kind === 'field') return sectionOf(doc, selection.id)?.id ?? null;
    return lastSectionId(doc);
  }, [doc, selection]);

  const handleAddField = useCallback(
    (type: FormFieldType) => {
      const sectionId = resolveTargetSection();
      if (!sectionId) return;
      const { doc: next, field } = insertField(doc, sectionId, type);
      emit(next);
      setSelection({ kind: 'field', id: field.id });
    },
    [doc, emit, resolveTargetSection],
  );

  // ---- dnd: palette → section, and field/section/page reorder ----
  const handleDragStart = useCallback((event: DragStartEvent) => {
    const data = event.active.data.current as
      | PaletteDragData
      | { type: 'field' | 'section' | 'page'; fieldId?: string }
      | undefined;
    if (data && 'source' in data && data.source === 'palette') {
      setDragLabel(fieldMeta(data.fieldType).label);
    } else {
      setDragLabel(null);
    }
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setDragLabel(null);
      const { active, over } = event;
      if (!over) return;

      type CanvasDragData = {
        type: 'field' | 'section' | 'page';
        fieldId?: string;
        sectionId?: string;
        pageId?: string;
      };
      const activeData = active.data.current as PaletteDragData | CanvasDragData | undefined;
      const overData = over.data.current as
        | { type: 'field' | 'section' | 'page' | 'section-empty'; sectionId?: string; pageId?: string }
        | undefined;
      if (!activeData) return;

      // Palette drop → insert into the target section.
      if ('source' in activeData && activeData.source === 'palette') {
        let sectionId: string | null = null;
        let index: number | undefined;
        if (overData?.type === 'section-empty') {
          sectionId = overData.sectionId ?? null;
        } else if (overData?.type === 'field') {
          const sec = sectionOf(doc, String(over.id));
          sectionId = sec?.id ?? null;
          index = sec ? sec.fields.findIndex((f) => f.id === over.id) + 1 : undefined;
        } else if (overData?.type === 'section') {
          sectionId = overData.sectionId ?? null;
        }
        if (!sectionId) return;
        const { doc: next, field } = insertField(doc, sectionId, activeData.fieldType, index);
        emit(next);
        setSelection({ kind: 'field', id: field.id });
        return;
      }

      if (active.id === over.id) return;

      const canvasData = activeData as CanvasDragData;

      // Field reorder / cross-section move.
      if (canvasData.type === 'field') {
        const fieldId = String(active.id);
        if (overData?.type === 'field') {
          const targetSection = sectionOf(doc, String(over.id));
          if (!targetSection) return;
          const overIndex = targetSection.fields.findIndex((f) => f.id === over.id);
          emit(moveField(doc, fieldId, targetSection.id, overIndex));
        } else if (overData?.type === 'section-empty' || overData?.type === 'section') {
          const targetSectionId = overData.sectionId;
          if (!targetSectionId) return;
          const target = doc.pages.flatMap((p) => p.sections).find((s) => s.id === targetSectionId);
          emit(moveField(doc, fieldId, targetSectionId, target?.fields.length ?? 0));
        }
        return;
      }

      // Section reorder within a page.
      if (canvasData.type === 'section' && overData?.type === 'section') {
        const page = doc.pages.find((p) => p.sections.some((s) => s.id === active.id));
        if (!page) return;
        const from = page.sections.findIndex((s) => s.id === active.id);
        const to = page.sections.findIndex((s) => s.id === over.id);
        if (from === -1 || to === -1) return;
        emit(moveSection(doc, page.id, from, to));
        return;
      }

      // Page reorder.
      if (canvasData.type === 'page' && overData?.type === 'page') {
        const from = doc.pages.findIndex((p) => p.id === active.id);
        const to = doc.pages.findIndex((p) => p.id === over.id);
        if (from === -1 || to === -1) return;
        emit(movePage(doc, from, to));
      }
    },
    [doc, emit],
  );

  // ---- field config callbacks (passed to SettingsPanel) ----
  const selectedFieldId = selection?.kind === 'field' ? selection.id : null;

  const configCallbacks = useMemo(
    () => ({
      onAddOption: () => selectedFieldId && emit(addOption(doc, selectedFieldId)),
      onUpdateOption: (index: number, patch: Partial<FormChoiceItem>) =>
        selectedFieldId && emit(updateOption(doc, selectedFieldId, index, patch)),
      onRemoveOption: (index: number) =>
        selectedFieldId && emit(removeOption(doc, selectedFieldId, index)),
      onMoveOption: (index: number, direction: -1 | 1) =>
        selectedFieldId && emit(moveOption(doc, selectedFieldId, index, direction)),
      onAddSubField: (type: FormSubFieldType) =>
        selectedFieldId && emit(addSubField(doc, selectedFieldId, type)),
      onUpdateSubField: (subId: string, patch: Partial<FormSubField>) =>
        selectedFieldId && emit(updateSubField(doc, selectedFieldId, subId, patch)),
      onRemoveSubField: (subId: string) =>
        selectedFieldId && emit(removeSubField(doc, selectedFieldId, subId)),
      onMoveSubField: (subId: string, direction: -1 | 1) =>
        selectedFieldId && emit(moveSubField(doc, selectedFieldId, subId, direction)),
    }),
    [doc, emit, selectedFieldId],
  );

  // ---- structural callbacks ----
  const handleDuplicateField = useCallback(
    (fieldId: string) => {
      const { doc: next, field } = duplicateField(doc, fieldId);
      emit(next);
      if (field) setSelection({ kind: 'field', id: field.id });
    },
    [doc, emit],
  );

  const handleRemoveField = useCallback(
    (fieldId: string) => {
      emit(removeField(doc, fieldId));
      setSelection((sel) => (sel?.kind === 'field' && sel.id === fieldId ? null : sel));
    },
    [doc, emit],
  );

  const handleAddFieldToSection = useCallback(
    (sectionId: string) => {
      const { doc: next, field } = insertField(doc, sectionId, 'text');
      emit(next);
      setSelection({ kind: 'field', id: field.id });
    },
    [doc, emit],
  );

  const handleRemoveSection = useCallback(
    (sectionId: string) => {
      emit(removeSection(doc, sectionId));
      setSelection((sel) => (sel?.kind === 'section' && sel.id === sectionId ? null : sel));
    },
    [doc, emit],
  );

  const handleAddSection = useCallback(
    (pageId: string) => {
      const { doc: next, section } = addSection(doc, pageId);
      emit(next);
      setSelection({ kind: 'section', id: section.id });
    },
    [doc, emit],
  );

  const handleRemovePage = useCallback(
    (pageId: string) => {
      emit(removePage(doc, pageId));
      setSelection((sel) => (sel?.kind === 'page' && sel.id === pageId ? null : sel));
    },
    [doc, emit],
  );

  const handleAddPage = useCallback(() => {
    const { doc: next, page } = addPage(doc);
    emit(next);
    setSelection({ kind: 'page', id: page.id });
  }, [doc, emit]);

  const canvasNode = (
    <Canvas
      doc={doc}
      editing={editing}
      selection={selection}
      onSelect={setSelection}
      onPageTitleChange={(pageId, title) => emit(updatePage(doc, pageId, { title }))}
      onSectionTitleChange={(sectionId, title) => emit(updateSection(doc, sectionId, { title }))}
      onDuplicateField={handleDuplicateField}
      onRemoveField={handleRemoveField}
      onAddFieldToSection={handleAddFieldToSection}
      onRemoveSection={handleRemoveSection}
      onAddSection={handleAddSection}
      onRemovePage={handleRemovePage}
      onAddPage={handleAddPage}
    />
  );

  return (
    <div data-testid="form-builder" className="flex flex-col gap-3">
      {editing && (
        <div className="flex items-center gap-0.5">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="Undo"
            title="Undo (⌘Z)"
            data-testid="form-undo"
            disabled={!canUndo}
            onClick={undo}
          >
            <Undo2 className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="Redo"
            title="Redo (⇧⌘Z)"
            data-testid="form-redo"
            disabled={!canRedo}
            onClick={redo}
          >
            <Redo2 className="size-4" />
          </Button>
        </div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={collisionDetection}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setDragLabel(null)}
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          {editing && (
            <aside className="w-full shrink-0 rounded-lg border border-input bg-background p-3 lg:h-[calc(100vh-220px)] lg:w-52 lg:overflow-y-auto">
              <Palette disabled={!editing} onAdd={handleAddField} />
            </aside>
          )}
          <main className="min-w-0 flex-1 rounded-lg bg-muted/40 p-4 lg:h-[calc(100vh-220px)] lg:overflow-y-auto">
            {canvasNode}
          </main>
          <aside className="w-full shrink-0 rounded-lg border border-input bg-background p-3 lg:h-[calc(100vh-220px)] lg:w-80 lg:overflow-y-auto">
            {editing ? (
              <SettingsPanel
                doc={doc}
                selection={selection}
                onPagePatch={(pageId, patch) => emit(updatePage(doc, pageId, patch))}
                onSectionPatch={(sectionId, patch: Partial<FormSection>) =>
                  emit(updateSection(doc, sectionId, patch))
                }
                onFieldPatch={(fieldId, patch: Partial<FormField>) =>
                  emit(updateField(doc, fieldId, patch))
                }
                onFieldTypeChange={(fieldId, type) => emit(changeFieldType(doc, fieldId, type))}
                config={configCallbacks}
              />
            ) : (
              <p className="px-1 py-8 text-center text-xs text-muted-foreground">
                Enable Edit to modify the form.
              </p>
            )}
          </aside>
        </div>
        <DragOverlay dropAnimation={null}>
          {dragLabel ? (
            <div className="pointer-events-none rounded-md border border-primary bg-background px-2.5 py-1.5 text-xs font-medium shadow-md">
              {dragLabel}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
