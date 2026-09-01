'use client';

import { ArrowDown, ArrowDownToLine, ArrowUp, ArrowUpToLine, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';
import { RuleBuilder } from '@/components/platform/rule-builder';
import { MergeInput } from '@/components/platform/email-editor/merge-input';
import { CANVAS_FONTS, mmToUnit, roundForUnit, unitToMm } from '@/lib/canvas-doc';
import type { RuleFact, RuleGroup } from '@/types/rules';
import type {
  CanvasElement,
  CanvasShapeKind,
  CanvasUnit,
  QrErrorCorrection,
  TemplateContextFact,
} from '@/types/templates';

export interface CanvasInspectorProps {
  element: CanvasElement | null;
  unit: CanvasUnit;
  mergeFields: TemplateContextFact[];
  visibilityFacts: RuleFact[];
  onChange: (patch: Partial<CanvasElement>) => void;
  onReorder: (delta: -1 | 1 | 'front' | 'back') => void;
  onRemove: () => void;
}

/** Geometry/property inspector (D15) - numeric inputs (mobile precision), z-order,
 * type props, merge binding, RuleBuilder visibility. Geometry shown in the
 * display unit; stored as mm. */
export function CanvasInspector({
  element,
  unit,
  mergeFields,
  visibilityFacts,
  onChange,
  onReorder,
  onRemove,
}: CanvasInspectorProps) {
  if (!element) {
    return (
      <div className="px-1 py-8 text-center text-xs text-muted-foreground">
        Select an element to edit it.
      </div>
    );
  }

  const num = (mmValue: number) => roundForUnit(mmToUnit(mmValue, unit), unit);
  const setMm = (key: 'x' | 'y' | 'w' | 'h', display: number) =>
    onChange({ [key]: roundForUnit(unitToMm(display, unit), 'mm') } as Partial<CanvasElement>);

  return (
    <div className="flex flex-col gap-4" data-testid="canvas-inspector">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {element.type}
        </span>
        <div className="flex gap-0.5">
          <IconBtn label="Bring forward" onClick={() => onReorder(1)} icon={ArrowUp} />
          <IconBtn label="Send backward" onClick={() => onReorder(-1)} icon={ArrowDown} />
          <IconBtn label="To front" onClick={() => onReorder('front')} icon={ArrowUpToLine} />
          <IconBtn label="To back" onClick={() => onReorder('back')} icon={ArrowDownToLine} />
        </div>
      </div>

      {/* Geometry (display unit) */}
      <div className="grid grid-cols-2 gap-2">
        <NumberField label={`X (${unit})`} value={num(element.x)} onChange={(v) => setMm('x', v)} />
        <NumberField label={`Y (${unit})`} value={num(element.y)} onChange={(v) => setMm('y', v)} />
        <NumberField label={`W (${unit})`} value={num(element.w)} onChange={(v) => setMm('w', v)} />
        <NumberField label={`H (${unit})`} value={num(element.h)} onChange={(v) => setMm('h', v)} />
        <NumberField
          label="Rotation (°)"
          value={element.rotation}
          onChange={(v) => onChange({ rotation: v })}
        />
      </div>

      {/* Type-specific props */}
      {element.type === 'text' && (
        <div className="flex flex-col gap-2">
          <Field label="Content">
            <MergeInput
              value={element.content}
              onChange={(content) => onChange({ content })}
              fields={mergeFields}
              multiline
              rows={2}
              aria-label="Text content"
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Font">
              <SearchSelect
                value={element.fontFamily}
                onChange={(v) => onChange({ fontFamily: v })}
                options={CANVAS_FONTS.map((f) => ({ label: f, value: f }))}
                ariaLabel="Font family"
              />
            </Field>
            <NumberField
              label="Size (pt)"
              value={element.fontSize}
              onChange={(fontSize) => onChange({ fontSize })}
            />
            <Field label="Weight">
              <SearchSelect
                value={String(element.weight)}
                onChange={(v) => onChange({ weight: Number(v) as 400 | 600 | 700 })}
                options={[
                  { label: 'Regular', value: '400' },
                  { label: 'Semibold', value: '600' },
                  { label: 'Bold', value: '700' },
                ]}
                ariaLabel="Font weight"
              />
            </Field>
            <Field label="Align">
              <SearchSelect
                value={element.align}
                onChange={(v) => onChange({ align: v as 'left' | 'center' | 'right' })}
                options={[
                  { label: 'Left', value: 'left' },
                  { label: 'Center', value: 'center' },
                  { label: 'Right', value: 'right' },
                ]}
                ariaLabel="Text align"
              />
            </Field>
          </div>
          <ColorField label="Color" value={element.color} onChange={(color) => onChange({ color })} />
        </div>
      )}

      {element.type === 'image' && (
        <div className="flex flex-col gap-2">
          <Field label="Image URL or merge field">
            <MergeInput
              value={element.src ?? ''}
              onChange={(src) => onChange({ src: src || null })}
              fields={mergeFields}
              aria-label="Image source"
              placeholder="https://… or {{logoUrl}}"
            />
          </Field>
          <Field label="Fit">
            <SearchSelect
              value={element.fit}
              onChange={(v) => onChange({ fit: v as 'contain' | 'cover' })}
              options={[
                { label: 'Contain', value: 'contain' },
                { label: 'Cover', value: 'cover' },
              ]}
              ariaLabel="Image fit"
            />
          </Field>
        </div>
      )}

      {element.type === 'shape' && (
        <div className="flex flex-col gap-2">
          <Field label="Shape">
            <SearchSelect
              value={element.kind}
              onChange={(v) => onChange({ kind: v as CanvasShapeKind })}
              options={[
                { label: 'Rectangle', value: 'rect' },
                { label: 'Ellipse', value: 'ellipse' },
                { label: 'Line', value: 'line' },
              ]}
              ariaLabel="Shape kind"
            />
          </Field>
          <ColorField
            label="Fill"
            value={element.fill ?? '#FF5A00'}
            onChange={(fill) => onChange({ fill })}
            onClear={() => onChange({ fill: null })}
          />
          <ColorField
            label="Stroke"
            value={element.stroke ?? '#18181B'}
            onChange={(stroke) => onChange({ stroke })}
            onClear={() => onChange({ stroke: null })}
          />
          <div className="grid grid-cols-2 gap-2">
            <NumberField
              label="Stroke (mm)"
              value={element.strokeWidth}
              onChange={(strokeWidth) => onChange({ strokeWidth })}
            />
            <NumberField
              label="Radius (mm)"
              value={element.radius}
              onChange={(radius) => onChange({ radius })}
            />
          </div>
        </div>
      )}

      {element.type === 'qr' && (
        <div className="flex flex-col gap-2">
          <Field label="QR data">
            <MergeInput
              value={element.data}
              onChange={(data) => onChange({ data })}
              fields={mergeFields}
              aria-label="QR data"
              placeholder="{{ticketCode}}"
            />
          </Field>
          <Field label="Error correction">
            <SearchSelect
              value={element.ecLevel}
              onChange={(v) => onChange({ ecLevel: v as QrErrorCorrection })}
              options={[
                { label: 'Low (L)', value: 'L' },
                { label: 'Medium (M)', value: 'M' },
                { label: 'Quartile (Q)', value: 'Q' },
                { label: 'High (H)', value: 'H' },
              ]}
              ariaLabel="QR error correction"
            />
          </Field>
        </div>
      )}

      {element.type === 'divider' && (
        <div className="flex flex-col gap-2">
          <ColorField label="Color" value={element.color} onChange={(color) => onChange({ color })} />
          <NumberField
            label="Thickness (mm)"
            value={element.thickness}
            onChange={(thickness) => onChange({ thickness })}
          />
        </div>
      )}

      {element.type === 'socialLinks' && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Renders your workspace social links (set in Branding).
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Align">
              <SearchSelect
                value={element.align}
                onChange={(v) => onChange({ align: v as 'left' | 'center' | 'right' })}
                options={[
                  { label: 'Left', value: 'left' },
                  { label: 'Center', value: 'center' },
                  { label: 'Right', value: 'right' },
                ]}
                ariaLabel="Social align"
              />
            </Field>
            <NumberField
              label="Size (px)"
              value={element.iconSize}
              onChange={(iconSize) => onChange({ iconSize })}
            />
          </div>
        </div>
      )}

      {element.type === 'customHtml' && (
        <Field label="HTML (sanitized at save)">
          <Textarea
            aria-label="Custom HTML"
            rows={6}
            className="font-mono text-xs"
            value={element.html}
            onChange={(e) => onChange({ html: e.target.value })}
          />
        </Field>
      )}

      {(element.type === 'brandHeader' || element.type === 'brandFooter') && (
        <p className="text-xs text-muted-foreground">
          {element.type === 'brandHeader'
            ? 'Renders your workspace logo on the brand colour - follows a rebrand automatically.'
            : 'Renders your workspace footer text + social links (set in Branding).'}
        </p>
      )}

      {/* Visibility - remount per element so the builder loads its own tree. */}
      <div className="flex flex-col gap-1.5 border-t border-input pt-3">
        <span className="text-xs font-medium text-muted-foreground">Visibility (optional)</span>
        <RuleBuilder
          key={element.id}
          facts={visibilityFacts}
          value={(element.conditionsJson as RuleGroup | null) ?? null}
          onChange={(group) => onChange({ conditionsJson: group })}
        />
      </div>

      <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onRemove}>
        <Trash2 className="size-3.5" /> Delete element
      </Button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label}>
      <Input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : 0);
        }}
        aria-label={label}
        className="h-8"
      />
    </Field>
  );
}

function ColorField({
  label,
  value,
  onChange,
  onClear,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onClear?: () => void;
}) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={label}
          className="h-8 w-10 cursor-pointer rounded border border-input bg-background"
        />
        <Input value={value} onChange={(e) => onChange(e.target.value)} className="h-8 flex-1" />
        {onClear && (
          <Button type="button" variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={onClear}>
            None
          </Button>
        )}
      </div>
    </Field>
  );
}

function IconBtn({
  label,
  onClick,
  icon: Icon,
}: {
  label: string;
  onClick: () => void;
  icon: typeof ArrowUp;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-7"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <Icon className="size-4" />
    </Button>
  );
}
