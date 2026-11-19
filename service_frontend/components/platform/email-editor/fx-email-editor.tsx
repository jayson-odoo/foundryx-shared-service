'use client';

/**
 * The email block editor with the Foundryx UIUX switch on (slice
 * W4-TEMPLATES). It edits the document through the same `useEmailEditor` as
 * the legacy look, with the same palette, canvas and settings panel, so the
 * saved document is the same for the same editing actions. What changes:
 * - Design / Preview is the playbook's segmented toggle; Undo and Redo are
 *   icon actions with tooltips.
 * - Playbook "Rich text fields > Preview": on the email surface, while
 *   designing, a live preview of the email as it is sent sits beside the
 *   design on wide screens and under it on narrower ones. It re-renders a
 *   moment after the last change (the same preview request the Preview tab
 *   makes; nothing is saved or sent). "Hide preview" folds it away.
 * - Not editing: no settings column and no "Enable Edit" hint (no
 *   instructional copy); the canvas takes the room.
 * - The document surface keeps its on-demand preview (a PDF render is heavy).
 */
import { useCallback, useEffect, useState } from 'react';
import { DndContext, DragOverlay } from '@dnd-kit/core';
import { Eye, EyeOff, PencilRuler, Redo2, Undo2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { FxToggleGroup, FxToggleGroupItem } from '@/components/fx/fields/fx-toggle-group';
import { MOCK_BRAND } from '@/lib/template-render';
import type { TemplateDocument } from '@/types/templates';
import { Canvas } from './canvas';
import { PageSetupPanel } from './page-setup-panel';
import { Palette } from './palette';
import { PdfPreviewPane } from './pdf-preview-pane';
import { SettingsPanel } from './settings-panel';
import { FxPreviewPane } from './fx-preview-pane';
import { collisionDetection, useEmailEditor } from './use-email-editor';
import type { EmailEditorProps } from './email-editor';

/** How long the live preview waits after the last change before it renders. */
export const FX_LIVE_PREVIEW_DELAY_MS = 800;

const PANEL = 'rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-3';

/** The document as it was `delay` ms after its last change. */
function useSettled<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return settled;
}

export function FxEmailEditor({
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

  const [livePreview, setLivePreview] = useState(true);
  const showLive = surface === 'email' && livePreview;
  const liveDoc = useSettled<TemplateDocument>(doc, FX_LIVE_PREVIEW_DELAY_MS);
  const renderLive = useCallback(() => renderPreview(liveDoc), [renderPreview, liveDoc]);

  return (
    <div data-testid="email-editor" data-fx-email-editor="" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <FxToggleGroup
          type="single"
          size="sm"
          aria-label="Design or preview"
          value={mode}
          onValueChange={(v) => v && setMode(v as 'design' | 'preview')}
        >
          <FxToggleGroupItem value="design" data-testid="editor-mode-design">
            <PencilRuler aria-hidden="true" className="size-3.5" /> Design
          </FxToggleGroupItem>
          <FxToggleGroupItem value="preview" data-testid="editor-mode-preview">
            <Eye aria-hidden="true" className="size-3.5" /> Preview
          </FxToggleGroupItem>
        </FxToggleGroup>
        {mode === 'design' && (
          <div className="ms-auto flex items-center gap-1">
            {editing && (
              <>
                <FxIconAction
                  mini
                  label="Undo"
                  icon="discard"
                  iconNode={<Undo2 aria-hidden="true" className="size-[18px]" />}
                  data-testid="editor-undo"
                  disabledReason={past.length === 0 ? 'Nothing to undo yet' : undefined}
                  onClick={undo}
                />
                <FxIconAction
                  mini
                  label="Redo"
                  icon="discard"
                  iconNode={<Redo2 aria-hidden="true" className="size-[18px]" />}
                  data-testid="editor-redo"
                  disabledReason={future.length === 0 ? 'Nothing to redo' : undefined}
                  onClick={redo}
                />
              </>
            )}
            {surface === 'email' && (
              <FxIconAction
                mini
                label={livePreview ? 'Hide preview' : 'Show preview beside'}
                icon="panel"
                iconNode={
                  livePreview ? (
                    <EyeOff aria-hidden="true" className="size-[18px]" />
                  ) : (
                    <Eye aria-hidden="true" className="size-[18px]" />
                  )
                }
                aria-pressed={livePreview}
                data-testid="editor-live-preview"
                onClick={() => setLivePreview((v) => !v)}
              />
            )}
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
          <FxPreviewPane render={() => renderPreview(doc)} />
        )
      ) : (
        <div
          className={cn(
            'flex flex-col gap-4',
            showLive && 'min-[1700px]:grid min-[1700px]:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] min-[1700px]:items-start',
          )}
        >
          <DndContext
            sensors={sensors}
            collisionDetection={collisionDetection}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragCancel={() => setDragLabel(null)}
          >
            <div className="flex min-w-0 flex-col items-stretch gap-4 lg:flex-row lg:items-start">
              {!structureLocked && editing && (
                <aside className={cn(PANEL, 'shrink-0 lg:w-44 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto')}>
                  <Palette disabled={!editing} surface={surface} />
                </aside>
              )}
              <main className="relative min-w-0 flex-1 rounded-(--fx-r-l) bg-(--fx-surface-2) px-4 py-6 sm:px-10">
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
              {editing && (
                <aside className={cn(PANEL, 'shrink-0 lg:w-80 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto')}>
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
                </aside>
              )}
            </div>
            {/* Floating chip following the pointer - drop feedback. */}
            <DragOverlay dropAnimation={null}>
              {dragLabel ? (
                <div className="pointer-events-none rounded-(--fx-r-m) border border-(--fx-link) bg-(--fx-surface) px-2.5 py-1.5 text-xs font-semibold text-(--fx-ink) shadow-md">
                  {dragLabel}
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
          {showLive && (
            <section aria-label="Email preview" className={cn(PANEL, 'min-w-0')} data-fx-live-preview="">
              <FxPreviewPane render={renderLive} initialWidth="mobile" compact />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
