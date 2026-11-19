'use client';

/**
 * The email block editor's state and actions (selection, Design / Preview,
 * undo and redo, drag and drop, every document change), shared by both looks
 * of `EmailEditor` so they edit the document the same way (Foundryx UIUX,
 * slice W4-TEMPLATES). Moved here unchanged from `email-editor.tsx`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  createBlock,
  createSection,
  changeSectionLayout,
  findBlock,
  findSection,
  insertBlock,
  insertSection,
  moveBlock,
  moveSection,
  removeBlock,
  removeSection,
  updateBlock,
  updateSection,
} from '@/lib/template-doc';
import type {
  PageSetup,
  SectionLayout,
  TemplateBlock,
  TemplateBlockType,
  TemplateDocument,
  TemplateSection,
} from '@/types/templates';
import type { EditorSelection } from './canvas';
import { labelForBlockType } from './palette';

/** Pointer hit first; fall back to rect overlap so near-misses still land. */
export const collisionDetection: CollisionDetection = (args) => {
  const pointer = pointerWithin(args);
  return pointer.length ? pointer : rectIntersection(args);
};

export function useEmailEditor({
  doc,
  onChange,
  editing,
}: {
  doc: TemplateDocument;
  onChange: (doc: TemplateDocument) => void;
  editing: boolean;
}) {
  const [selection, setSelection] = useState<EditorSelection>(null);
  const [mode, setMode] = useState<'design' | 'preview'>('design');
  const [dragLabel, setDragLabel] = useState<string | null>(null);

  // ---- Undo/redo history (client-side, buffered like the canvas itself) ----
  const [past, setPast] = useState<TemplateDocument[]>([]);
  const [future, setFuture] = useState<TemplateDocument[]>([]);
  // Last doc WE emitted - a prop change that isn't ours (load, Cancel/discard)
  // belongs to a different timeline: reset the stacks.
  const lastEmitted = useRef<TemplateDocument | null>(null);

  useEffect(() => {
    if (lastEmitted.current !== null && doc !== lastEmitted.current) {
      setPast([]);
      setFuture([]);
      lastEmitted.current = null;
    }
  }, [doc]);

  const emit = useCallback(
    (next: TemplateDocument) => {
      lastEmitted.current = next;
      setPast((p) => [...p, doc]);
      setFuture([]);
      onChange(next);
    },
    [doc, onChange],
  );

  const undo = useCallback(() => {
    setPast((p) => {
      if (!p.length) return p;
      const prev = p[p.length - 1];
      lastEmitted.current = prev;
      setFuture((f) => [doc, ...f]);
      onChange(prev);
      return p.slice(0, -1);
    });
  }, [doc, onChange]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (!f.length) return f;
      const next = f[0];
      lastEmitted.current = next;
      setPast((p) => [...p, doc]);
      onChange(next);
      return f.slice(1);
    });
  }, [doc, onChange]);

  // Cmd/Ctrl+Z / Shift+Cmd+Z / Ctrl+Y - but never hijack native text-undo
  // inside an active text field or inline-editable block.
  useEffect(() => {
    if (!editing || mode !== 'design') return;
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'z') {
        if (!((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'y')) return;
      }
      const target = e.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      e.preventDefault();
      if (e.key.toLowerCase() === 'y' || e.shiftKey) redo();
      else undo();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, mode, undo, redo]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const data = event.active.data.current as
        | { source: 'palette'; blockType: TemplateBlockType }
        | { source: 'canvas'; blockId: string }
        | undefined;
      if (data?.source === 'palette') {
        setDragLabel(labelForBlockType(data.blockType));
      } else if (data?.source === 'canvas') {
        const found = findBlock(doc, data.blockId);
        setDragLabel(found ? labelForBlockType(found.block.type) : null);
      }
    },
    [doc],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setDragLabel(null);
      const over = event.over;
      if (!over) return;
      const target = over.data.current as
        | { target: 'gap'; sectionId: string; columnId: string; index: number }
        | undefined;
      if (!target || target.target !== 'gap') return;

      const source = event.active.data.current as
        | { source: 'palette'; blockType: TemplateBlockType }
        | { source: 'canvas'; blockId: string }
        | undefined;
      if (!source) return;

      if (source.source === 'palette') {
        const block = createBlock(source.blockType);
        emit(insertBlock(doc, target.sectionId, target.columnId, block, target.index));
        setSelection({ kind: 'block', id: block.id });
      } else {
        emit(
          moveBlock(doc, source.blockId, {
            sectionId: target.sectionId,
            columnId: target.columnId,
            index: target.index,
          }),
        );
      }
    },
    [doc, emit],
  );

  const handleBlockChange = useCallback(
    (blockId: string, patch: Partial<TemplateBlock>) => emit(updateBlock(doc, blockId, patch)),
    [doc, emit],
  );

  const handleSectionChange = useCallback(
    (sectionId: string, patch: Partial<TemplateSection>) =>
      emit(updateSection(doc, sectionId, patch)),
    [doc, emit],
  );

  const handleSectionLayoutChange = useCallback(
    (sectionId: string, layout: SectionLayout) =>
      emit(changeSectionLayout(doc, sectionId, layout)),
    [doc, emit],
  );

  const handleRemoveBlock = useCallback(
    (blockId: string) => {
      emit(removeBlock(doc, blockId));
      setSelection(null);
    },
    [doc, emit],
  );

  const handleAddSection = useCallback(
    (index: number) => {
      const section = createSection('100');
      emit(insertSection(doc, section, index));
      setSelection({ kind: 'section', id: section.id });
    },
    [doc, emit],
  );

  const handleMoveSection = useCallback(
    (sectionId: string, direction: -1 | 1) => {
      const from = doc.sections.findIndex((s) => s.id === sectionId);
      if (from === -1) return;
      emit(moveSection(doc, sectionId, direction === -1 ? from - 1 : from + 2));
    },
    [doc, emit],
  );

  const handleRemoveSection = useCallback(
    (sectionId: string) => {
      emit(removeSection(doc, sectionId));
      setSelection(null);
    },
    [doc, emit],
  );

  const handlePageSetupChange = useCallback(
    (pageSetup: PageSetup) => emit({ ...doc, pageSetup }),
    [doc, emit],
  );

  const resolvedSelection = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === 'block') {
      const found = findBlock(doc, selection.id);
      return found ? ({ kind: 'block', block: found.block } as const) : null;
    }
    const section = findSection(doc, selection.id);
    return section ? ({ kind: 'section', section } as const) : null;
  }, [doc, selection]);

  return {
    selection,
    setSelection,
    mode,
    setMode,
    dragLabel,
    setDragLabel,
    past,
    future,
    undo,
    redo,
    sensors,
    handleDragStart,
    handleDragEnd,
    handleBlockChange,
    handleSectionChange,
    handleSectionLayoutChange,
    handleRemoveBlock,
    handleAddSection,
    handleMoveSection,
    handleRemoveSection,
    handlePageSetupChange,
    resolvedSelection,
  };
}
