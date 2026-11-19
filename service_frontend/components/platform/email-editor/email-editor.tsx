'use client';

import { DndContext, DragOverlay } from '@dnd-kit/core';
import { Eye, PencilRuler, Redo2, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useFx } from '@/hooks/use-fx';
import { MOCK_BRAND, type BrandRenderValues } from '@/lib/template-render';
import type { TemplatePreview } from '@/services/template-service';
import type { RuleFact } from '@/types/rules';
import type { TemplateContextFact, TemplateDocument, TemplateListFact } from '@/types/templates';
import { Canvas } from './canvas';
import { PageSetupPanel } from './page-setup-panel';
import { Palette } from './palette';
import { PreviewPane } from './preview-pane';
import { PdfPreviewPane } from './pdf-preview-pane';
import { SettingsPanel } from './settings-panel';
import { collisionDetection, useEmailEditor } from './use-email-editor';
import { FxEmailEditor } from './fx-email-editor';

/** Render surface: email (instant HTML preview) or document (on-demand PDF). */
export type EditorSurface = 'email' | 'document';

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

export function EmailEditor(props: EmailEditorProps) {
  // Foundryx UIUX switch: the playbook's toolbar and the live preview beside
  // the design while on; today's editor while off. Both edit the document
  // through the same `useEmailEditor`.
  return useFx() ? <FxEmailEditor {...props} /> : <EmailEditorLegacy {...props} />;
}

function EmailEditorLegacy({
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
  const {
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
  } = useEmailEditor({ doc, onChange, editing });

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
