'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { Eye, PencilRuler, Redo2, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { MOCK_BRAND, type BrandRenderValues } from '@/lib/template-render';
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
import type { TemplatePreview } from '@/services/template-service';
import type { RuleFact } from '@/types/rules';
import type {
  PageSetup,
  SectionLayout,
  TemplateBlock,
  TemplateBlockType,
  TemplateContextFact,
  TemplateDocument,
  TemplateListFact,
  TemplateSection,
} from '@/types/templates';
import { Canvas, type EditorSelection } from './canvas';
import { PageSetupPanel } from './page-setup-panel';
import { labelForBlockType, Palette } from './palette';
import { PreviewPane } from './preview-pane';
import { PdfPreviewPane } from './pdf-preview-pane';
import { SettingsPanel } from './settings-panel';

/** Render surface: email (instant HTML preview) or document (on-demand PDF). */
export type EditorSurface = 'email' | 'document';

/** Pointer hit first; fall back to rect overlap so near-misses still land. */
const collisionDetection: CollisionDetection = (args) => {
  const pointer = pointerWithin(args);
  return pointer.length ? pointer : rectIntersection(args);
};

/**
 * The email block editor (plan sprint-2/07 D2/D12) - editor-agnostic JSON
 * doc in/out; the schema in types/templates.ts is the only contract.
 */
export interface EmailEditorProps {
  doc: TemplateDocument;
  onChange: (doc: TemplateDocument) => void;
  /** Global Edit toggle (ResourceForm) gates every mutation - FlowCanvas precedent. */
  editing: boolean;
  /** Merge-field vocabulary of the template's context (chips + tokens). */
  mergeFields: TemplateContextFact[];
  /** Rule-engine facts for block/section visibility conditions (D8). */
  visibilityFacts: RuleFact[];
  /** Render pipeline for the (email) preview pane (mock now, backend in Phase B). */
  renderPreview: (doc: TemplateDocument) => Promise<TemplatePreview>;
  /** Brand values for canvas approximation (logo, colors, socials). */
  brand?: BrandRenderValues;
  /**
   * Render surface (F2 D3). 'email' (default) = block palette + instant HTML
   * preview. 'document' = document palette (table/repeater) + a page-setup
   * panel + an on-demand embedded PDF preview.
   */
  surface?: EditorSurface;
  /**
   * List facts (document surface) bindable by table/repeater blocks - drives
   * the source pickers + row.* item-field pickers. Ignored on the email surface.
   */
  listFacts?: TemplateListFact[];
  /**
   * Document surface: render the draft to the in-app preview HTML sheet
   * (on-demand "Refresh preview"). Required when `surface==='document'`.
   */
  renderDocHtml?: (doc: TemplateDocument) => Promise<string>;
  /** Document surface: fetch the authoritative PDF bytes for download. */
  renderPdf?: (doc: TemplateDocument) => Promise<Blob>;
  /**
   * Content-only mode (per-use template copy): edit WORDING in place, but the
   * STRUCTURE is locked - no palette, no add/reorder/delete of sections/blocks
   * (rearranging the layout belongs in the Templates engine). Default false.
   */
  structureLocked?: boolean;
}

export function EmailEditor({
  doc,
  onChange,
  editing,
  mergeFields,
  visibilityFacts,
  renderPreview,
  brand = MOCK_BRAND,
  structureLocked = false,
  surface = 'email',
  listFacts = [],
  renderDocHtml,
  renderPdf,
}: EmailEditorProps) {
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

  return (
    <div data-testid="email-editor" className="flex flex-col gap-3">
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant={mode === 'design' ? 'primary' : 'outline'}
          size="sm"
          data-testid="editor-mode-design"
          onClick={() => setMode('design')}
        >
          <PencilRuler className="size-3.5" /> Design
        </Button>
        <Button
          type="button"
          variant={mode === 'preview' ? 'primary' : 'outline'}
          size="sm"
          data-testid="editor-mode-preview"
          onClick={() => setMode('preview')}
        >
          <Eye className="size-3.5" /> Preview
        </Button>
        {/* Undo/redo in the toolbar - consistent with the form + workflow + canvas
            editors. ⌘Z / ⇧⌘Z / Ctrl+Y also work. */}
        {mode === 'design' && editing && (
          <div className="ml-auto flex gap-0.5 rounded-md border border-input bg-background p-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Undo"
              title="Undo (⌘Z)"
              data-testid="editor-undo"
              disabled={past.length === 0}
              onClick={undo}
            >
              <Undo2 className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Redo"
              title="Redo (⇧⌘Z)"
              data-testid="editor-redo"
              disabled={future.length === 0}
              onClick={redo}
            >
              <Redo2 className="size-4" />
            </Button>
          </div>
        )}
      </div>

      {mode === 'preview' ? (
        surface === 'document' && renderDocHtml ? (
          <PdfPreviewPane
            renderHtml={() => renderDocHtml(doc)}
            downloadPdf={renderPdf ? () => renderPdf(doc) : undefined}
          />
        ) : (
          <PreviewPane render={() => renderPreview(doc)} />
        )
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={collisionDetection}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setDragLabel(null)}
        >
          <div className="flex flex-col items-stretch gap-4 lg:flex-row lg:items-start">
            {!structureLocked && (
              <aside className="shrink-0 rounded-lg border border-input bg-background p-3 lg:w-44 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto">
                <Palette disabled={!editing} surface={surface} />
              </aside>
            )}
            <main className="relative min-w-0 flex-1 rounded-lg bg-zinc-100 px-4 py-6 sm:px-10 dark:bg-zinc-900">
              <Canvas
                doc={doc}
                editing={editing}
                surface={surface}
                structureLocked={structureLocked}
                selection={selection}
                brand={brand}
                listFacts={listFacts}
                onSelect={setSelection}
                onInlineChange={handleBlockChange}
                onAddSection={handleAddSection}
                onMoveSection={handleMoveSection}
                onRemoveSection={handleRemoveSection}
              />
            </main>
            <aside className="shrink-0 rounded-lg border border-input bg-background p-3 lg:w-80 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto">
              {editing ? (
                <div className="flex flex-col gap-4">
                  {surface === 'document' && (
                    <PageSetupPanel value={doc.pageSetup ?? null} onChange={handlePageSetupChange} />
                  )}
                  <SettingsPanel
                    selection={resolvedSelection}
                    mergeFields={mergeFields}
                    visibilityFacts={visibilityFacts}
                    structureLocked={structureLocked}
                    listFacts={listFacts}
                    onBlockChange={handleBlockChange}
                    onSectionChange={handleSectionChange}
                    onSectionLayoutChange={handleSectionLayoutChange}
                    onRemoveBlock={handleRemoveBlock}
                  />
                </div>
              ) : (
                <div className="px-1 py-8 text-center text-xs text-muted-foreground">
                  Enable Edit to modify the design.
                </div>
              )}
            </aside>
          </div>
          {/* Floating chip following the pointer - drop feedback. */}
          <DragOverlay dropAnimation={null}>
            {dragLabel ? (
              <div className="pointer-events-none rounded-md border border-primary bg-background px-2.5 py-1.5 text-xs font-medium shadow-md">
                {dragLabel}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  );
}
