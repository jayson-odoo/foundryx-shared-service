'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { Eye, PencilRuler, Plus, Redo2, Trash2, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { PdfPreviewPane } from '@/components/platform/email-editor/pdf-preview-pane';
import { useHistory } from '@/components/platform/flow-canvas/use-history';
import {
  addElement,
  addSide,
  CANVAS_FONTS,
  clampElementPatch,
  createCanvasElement,
  findElement,
  removeElement,
  removeSide,
  reorderElement,
  roundForUnit,
  updateCanvas,
  updateElement,
} from '@/lib/canvas-doc';
import type { RuleFact } from '@/types/rules';
import type {
  CanvasDocument,
  CanvasElement,
  CanvasElementType,
  CanvasUnit,
  TemplateContextFact,
} from '@/types/templates';
import { CanvasPalette } from './palette';
import { CanvasInspector } from './inspector';

// Konva touches the DOM canvas - never SSR it.
const CanvasStage = dynamic(() => import('./stage').then((m) => m.CanvasStage), {
  ssr: false,
  loading: () => (
    <div className="flex h-64 items-center justify-center rounded-md bg-zinc-100 text-sm text-muted-foreground dark:bg-zinc-900">
      Loading canvas…
    </div>
  ),
});

export interface CanvasEditorProps {
  doc: CanvasDocument;
  onChange: (doc: CanvasDocument) => void;
  /** Global Edit toggle gates every mutation (ResourceForm precedent). */
  editing: boolean;
  /** Merge-field vocabulary of the template's context (binding). */
  mergeFields: TemplateContextFact[];
  /** Rule-engine facts for element visibility conditions. */
  visibilityFacts: RuleFact[];
  /** Render the draft canvas doc to the in-app preview HTML (on-demand). */
  renderCanvasHtml: (doc: CanvasDocument) => Promise<string>;
  /** Fetch the authoritative PDF bytes for download. */
  renderCanvasPdf: (doc: CanvasDocument) => Promise<Blob>;
}

const UNIT_OPTIONS = [
  { label: 'mm', value: 'mm' },
  { label: 'in', value: 'in' },
  { label: 'px', value: 'px' },
];

export function CanvasEditor({
  doc,
  onChange,
  editing,
  mergeFields,
  visibilityFacts,
  renderCanvasHtml,
  renderCanvasPdf,
}: CanvasEditorProps) {
  const history = useHistory<CanvasDocument>(doc, onChange);
  const [mode, setMode] = useState<'design' | 'preview'>('design');
  const [sideIndex, setSideIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Load the bundled families so the Konva canvas renders the chosen font (the
  // server preview is authoritative; this is editor fidelity). Once per app.
  useEffect(() => {
    const id = 'canvas-editor-fonts';
    if (document.getElementById(id)) return;
    const link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href =
      'https://fonts.googleapis.com/css2?' +
      CANVAS_FONTS.map((f) => `family=${f.replace(/ /g, '+')}:wght@400;700`).join('&') +
      '&display=swap';
    document.head.appendChild(link);
  }, []);

  const unit = doc.canvas.unit;
  const safeSide = Math.min(sideIndex, doc.sides.length - 1);
  const selected = useMemo(
    () => (selectedId ? findElement(doc, safeSide, selectedId) : null),
    [doc, safeSide, selectedId],
  );

  // ---- mutations (all through history) ----
  const handleAdd = useCallback(
    (type: CanvasElementType) => {
      const el = createCanvasElement(type, doc.canvas);
      history.set(addElement(doc, safeSide, el));
      setSelectedId(el.id);
    },
    [doc, safeSide, history],
  );

  const handleElementChange = useCallback(
    (patch: Partial<CanvasElement>) => {
      if (!selectedId || !selected) return;
      // No element may exceed the canvas - clamp any geometry change.
      history.set(updateElement(doc, safeSide, selectedId, clampElementPatch(doc.canvas, selected, patch)));
    },
    [doc, safeSide, selectedId, selected, history],
  );

  const handleGeometry = useCallback(
    (id: string, patch: Partial<CanvasElement>) => {
      const el = findElement(doc, safeSide, id);
      const clamped = el ? clampElementPatch(doc.canvas, el, patch) : patch;
      history.set(updateElement(doc, safeSide, id, clamped));
    },
    [doc, safeSide, history],
  );

  const handleReorder = useCallback(
    (delta: -1 | 1 | 'front' | 'back') => {
      if (!selectedId) return;
      history.set(reorderElement(doc, safeSide, selectedId, delta));
    },
    [doc, safeSide, selectedId, history],
  );

  const handleRemove = useCallback(() => {
    if (!selectedId) return;
    history.set(removeElement(doc, safeSide, selectedId));
    setSelectedId(null);
  }, [doc, safeSide, selectedId, history]);

  const handleCanvasChange = useCallback(
    (patch: Partial<CanvasDocument['canvas']>) => history.set(updateCanvas(doc, patch)),
    [doc, history],
  );

  // ---- keyboard: undo/redo, delete, nudge (focus-guarded) ----
  useEffect(() => {
    if (!editing || mode !== 'design') return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      // Skip when focus is on ANY interactive control (SearchSelect triggers are
      // buttons - a reflexive Backspace must not destroy an element mid-config).
      if (target?.closest('input, textarea, [contenteditable="true"], [role="combobox"], button'))
        return;
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) history.redo();
        else history.undo();
        return;
      }
      if (meta && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        history.redo();
        return;
      }
      if (!selectedId || !selected) return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        handleRemove();
        return;
      }
      const step = e.shiftKey ? 0.2 : 1;
      const round = (v: number) => roundForUnit(v, 'mm');
      const nudges: Record<string, Partial<CanvasElement>> = {
        ArrowLeft: { x: round(selected.x - step) },
        ArrowRight: { x: round(selected.x + step) },
        ArrowUp: { y: round(selected.y - step) },
        ArrowDown: { y: round(selected.y + step) },
      };
      if (nudges[e.key]) {
        e.preventDefault();
        history.set(
          updateElement(doc, safeSide, selectedId, clampElementPatch(doc.canvas, selected, nudges[e.key])),
        );
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [editing, mode, selectedId, selected, doc, safeSide, history, handleRemove]);

  return (
    <div data-testid="canvas-editor" className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1">
        <Button
          type="button"
          variant={mode === 'design' ? 'primary' : 'outline'}
          size="sm"
          data-testid="canvas-mode-design"
          onClick={() => setMode('design')}
        >
          <PencilRuler className="size-3.5" /> Design
        </Button>
        <Button
          type="button"
          variant={mode === 'preview' ? 'primary' : 'outline'}
          size="sm"
          data-testid="canvas-mode-preview"
          onClick={() => setMode('preview')}
        >
          <Eye className="size-3.5" /> Preview
        </Button>
        {mode === 'design' && editing && (
          <div className="ml-auto flex gap-0.5 rounded-md border border-input bg-background p-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Undo"
              title="Undo (⌘Z)"
              data-testid="canvas-undo"
              disabled={!history.canUndo}
              onClick={history.undo}
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
              data-testid="canvas-redo"
              disabled={!history.canRedo}
              onClick={history.redo}
            >
              <Redo2 className="size-4" />
            </Button>
          </div>
        )}
      </div>

      {mode === 'preview' ? (
        <PdfPreviewPane
          renderHtml={() => renderCanvasHtml(doc)}
          downloadPdf={() => renderCanvasPdf(doc)}
        />
      ) : (
        <div className="flex flex-col items-stretch gap-4 lg:flex-row lg:items-start">
          {/* Left: palette + canvas settings */}
          <aside className="flex shrink-0 flex-col gap-4 rounded-lg border border-input bg-background p-3 lg:w-52 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto">
            <CanvasPalette disabled={!editing} onAdd={handleAdd} />
            <CanvasSettings
              canvas={doc.canvas}
              disabled={!editing}
              onChange={handleCanvasChange}
            />
            <SideSwitcher
              sides={doc.sides.map((s) => s.name)}
              active={safeSide}
              disabled={!editing}
              onSelect={(i) => {
                setSideIndex(i);
                setSelectedId(null);
              }}
              onAdd={() => {
                history.set(addSide(doc));
                setSideIndex(doc.sides.length);
                setSelectedId(null);
              }}
              onRemove={(i) => {
                history.set(removeSide(doc, i));
                setSideIndex(0);
                setSelectedId(null);
              }}
            />
          </aside>

          {/* Centre: canvas */}
          <main className="min-w-0 flex-1">
            <CanvasStage
              doc={doc}
              sideIndex={safeSide}
              selectedId={selectedId}
              editing={editing}
              onSelect={setSelectedId}
              onGeometry={handleGeometry}
            />
          </main>

          {/* Right: inspector */}
          <aside className="shrink-0 rounded-lg border border-input bg-background p-3 lg:w-80 lg:max-h-[calc(100vh-12rem)] lg:overflow-y-auto">
            {editing ? (
              <CanvasInspector
                element={selected}
                unit={unit}
                mergeFields={mergeFields}
                visibilityFacts={visibilityFacts}
                onChange={handleElementChange}
                onReorder={handleReorder}
                onRemove={handleRemove}
              />
            ) : (
              <div className="px-1 py-8 text-center text-xs text-muted-foreground">
                Enable Edit to modify the design.
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function CanvasSettings({
  canvas,
  disabled,
  onChange,
}: {
  canvas: CanvasDocument['canvas'];
  disabled?: boolean;
  onChange: (patch: Partial<CanvasDocument['canvas']>) => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-t border-input pt-3">
      <span className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Canvas
      </span>
      <div className="grid grid-cols-2 gap-2">
        <SmallNum label="Width (mm)" value={canvas.width} disabled={disabled} onChange={(width) => onChange({ width })} />
        <SmallNum label="Height (mm)" value={canvas.height} disabled={disabled} onChange={(height) => onChange({ height })} />
        <SmallNum label="Bleed (mm)" value={canvas.bleed} disabled={disabled} onChange={(bleed) => onChange({ bleed })} />
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Unit</Label>
          <SearchSelect
            value={canvas.unit}
            onChange={(v) => onChange({ unit: v as CanvasUnit })}
            options={UNIT_OPTIONS}
            disabled={disabled}
            ariaLabel="Display unit"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">Orientation</Label>
        <SearchSelect
          value={canvas.orientation}
          onChange={(v) => {
            const orientation = v as 'portrait' | 'landscape';
            if (orientation === canvas.orientation) return;
            // Orientation flip swaps the physical page dimensions so width/height
            // stay authoritative (the render never re-swaps - keeps editor↔PDF
            // parity). Element positions are intentionally left as-is.
            onChange({ orientation, width: canvas.height, height: canvas.width });
          }}
          options={[
            { label: 'Landscape', value: 'landscape' },
            { label: 'Portrait', value: 'portrait' },
          ]}
          disabled={disabled}
          ariaLabel="Orientation"
        />
      </div>
    </div>
  );
}

function SideSwitcher({
  sides,
  active,
  disabled,
  onSelect,
  onAdd,
  onRemove,
}: {
  sides: string[];
  active: number;
  disabled?: boolean;
  onSelect: (i: number) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-t border-input pt-3">
      <span className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Sides
      </span>
      <div className="flex flex-wrap gap-1">
        {sides.map((name, i) => (
          <Button
            key={i}
            type="button"
            variant={i === active ? 'primary' : 'outline'}
            size="sm"
            className="h-7 capitalize"
            data-testid={`canvas-side-${i}`}
            onClick={() => onSelect(i)}
          >
            {name}
          </Button>
        ))}
        {!disabled && sides.length < 2 && (
          <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Add back side" onClick={onAdd}>
            <Plus className="size-4" />
          </Button>
        )}
        {!disabled && sides.length > 1 && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label="Remove side"
            onClick={() => onRemove(active)}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

function SmallNum({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input
        type="number"
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (Number.isFinite(v) && v > 0) onChange(v);
        }}
        aria-label={label}
        className="h-8"
      />
    </div>
  );
}
