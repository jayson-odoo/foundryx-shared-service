import { TEMPLATE_SCHEMA_VERSION } from '@/types/templates';
import type {
  CanvasDocument,
  CanvasElement,
  CanvasElementType,
  CanvasSide,
  CanvasSize,
  CanvasUnit,
} from '@/types/templates';
import { newDocId } from '@/lib/template-doc';

// ---------------------------------------------------------------------------
// F2 slice 2 - fixed-canvas (badge/ticket/cert) doc helpers
// ---------------------------------------------------------------------------
// Geometry is ALWAYS stored in mm (print-authoritative). `canvas.unit` is the
// editor's display/input unit only - convert on the boundary, never in the doc.

/** Bundled font families (mirror of backend fonts.py FONT_NAMES) - the canvas
 * text font picker. Adding a family = bundle the TTF + register on BOTH sides. */
export const CANVAS_FONTS = [
  'Inter',
  'Poppins',
  'Roboto',
  'Montserrat',
  'Lato',
  'Open Sans',
  'Merriweather',
  'Playfair Display',
  'Oswald',
  'Roboto Mono',
] as const;

/** Default badge: 86×54mm landscape (CR80 card), 3mm bleed, one front side. */
export const DEFAULT_BADGE_SIZE: CanvasSize = {
  width: 86,
  height: 54,
  unit: 'mm',
  orientation: 'landscape',
  bleed: 3,
};

/** Factory: a new element of `type` with house defaults, centred in `size`. */
export function createCanvasElement(type: CanvasElementType, size: CanvasSize): CanvasElement {
  const id = newDocId('el');
  const w = type === 'qr' ? 20 : 40;
  const h = type === 'qr' ? 20 : type === 'text' ? 10 : 24;
  const x = Math.max(0, size.width / 2 - w / 2);
  const y = Math.max(0, size.height / 2 - h / 2);
  const base = { id, x, y, w, h, rotation: 0 } as const;
  switch (type) {
    case 'text':
      return {
        ...base,
        type,
        content: 'Text',
        fontFamily: 'Inter',
        fontSize: 12,
        weight: 400,
        align: 'left',
        color: '#18181B',
        lineHeight: 1.3,
      };
    case 'image':
      return { ...base, type, storageKey: null, src: null, fit: 'contain' };
    case 'shape':
      return { ...base, type, kind: 'rect', fill: '#FF5A00', stroke: null, strokeWidth: 0, radius: 0 };
    case 'qr':
      return { ...base, type, data: '', ecLevel: 'M' };
    case 'divider':
      return { ...base, type, h: 2, color: '#E4E4E7', thickness: 0.4 };
    case 'socialLinks':
      return { ...base, type, links: null, align: 'center', iconSize: 12 };
    case 'customHtml':
      return { ...base, type, html: '' };
    case 'brandHeader':
      return { ...base, type, h: 12, overrides: null };
    case 'brandFooter':
      return { ...base, type, h: 8, overrides: null };
  }
}

/** A blank badge canvas doc (one front side, default CR80 size). */
export function createBlankBadgeDoc(): CanvasDocument {
  return {
    schemaVersion: TEMPLATE_SCHEMA_VERSION,
    canvas: { ...DEFAULT_BADGE_SIZE },
    sides: [{ name: 'front', elements: [] }],
  };
}

// ---- unit conversion (display ⇄ mm) ---------------------------------------

const MM_PER_IN = 25.4;
const PX_PER_IN = 96; // CSS reference pixel

/** Convert a mm value to the display unit. */
export function mmToUnit(mm: number, unit: CanvasUnit): number {
  if (unit === 'in') return mm / MM_PER_IN;
  if (unit === 'px') return (mm / MM_PER_IN) * PX_PER_IN;
  return mm;
}

/** Convert a display-unit value back to mm (stored geometry). */
export function unitToMm(value: number, unit: CanvasUnit): number {
  if (unit === 'in') return value * MM_PER_IN;
  if (unit === 'px') return (value / PX_PER_IN) * MM_PER_IN;
  return value;
}

/** Round to a sensible precision for the display unit (mm/px: 1dp, in: 3dp). */
export function roundForUnit(value: number, unit: CanvasUnit): number {
  const dp = unit === 'in' ? 3 : 1;
  const f = 10 ** dp;
  return Math.round(value * f) / f;
}

// ---- containment: no element may exceed the canvas (the page) -------------

/** Clamp an axis-aligned box to the canvas trim [0..width] × [0..height].
 * Size is capped to the canvas first, then position so the box stays inside.
 * (Rotation is ignored - the unrotated box is what's bounded.) */
export function clampBox(
  canvas: CanvasSize,
  x: number,
  y: number,
  w: number,
  h: number,
): { x: number; y: number; w: number; h: number } {
  const cw = Math.min(Math.max(w, 1), canvas.width);
  const ch = Math.min(Math.max(h, 1), canvas.height);
  const cx = Math.min(Math.max(x, 0), canvas.width - cw);
  const cy = Math.min(Math.max(y, 0), canvas.height - ch);
  return {
    x: roundForUnit(cx, 'mm'),
    y: roundForUnit(cy, 'mm'),
    w: roundForUnit(cw, 'mm'),
    h: roundForUnit(ch, 'mm'),
  };
}

/** If `patch` touches geometry, return it with x/y/w/h clamped to the canvas
 * (merged over `element`); otherwise the patch unchanged. */
export function clampElementPatch(
  canvas: CanvasSize,
  element: CanvasElement,
  patch: Partial<CanvasElement>,
): Partial<CanvasElement> {
  if (!('x' in patch || 'y' in patch || 'w' in patch || 'h' in patch)) return patch;
  const m = { ...element, ...patch } as CanvasElement;
  return { ...patch, ...clampBox(canvas, m.x, m.y, m.w, m.h) };
}

// ---- immutable mutations (the editor's only mutation surface) -------------

export function updateCanvas(doc: CanvasDocument, patch: Partial<CanvasSize>): CanvasDocument {
  return { ...doc, canvas: { ...doc.canvas, ...patch } };
}

function mapSide(
  doc: CanvasDocument,
  sideIndex: number,
  fn: (side: CanvasSide) => CanvasSide,
): CanvasDocument {
  return { ...doc, sides: doc.sides.map((s, i) => (i === sideIndex ? fn(s) : s)) };
}

export function addElement(
  doc: CanvasDocument,
  sideIndex: number,
  element: CanvasElement,
): CanvasDocument {
  return mapSide(doc, sideIndex, (s) => ({ ...s, elements: [...s.elements, element] }));
}

export function updateElement(
  doc: CanvasDocument,
  sideIndex: number,
  elementId: string,
  patch: Partial<CanvasElement>,
): CanvasDocument {
  return mapSide(doc, sideIndex, (s) => ({
    ...s,
    elements: s.elements.map((el) =>
      el.id === elementId ? ({ ...el, ...patch } as CanvasElement) : el,
    ),
  }));
}

export function removeElement(
  doc: CanvasDocument,
  sideIndex: number,
  elementId: string,
): CanvasDocument {
  return mapSide(doc, sideIndex, (s) => ({
    ...s,
    elements: s.elements.filter((el) => el.id !== elementId),
  }));
}

/** Move an element in z-order (array order). `delta` -1 = back, +1 = forward. */
export function reorderElement(
  doc: CanvasDocument,
  sideIndex: number,
  elementId: string,
  delta: -1 | 1 | 'front' | 'back',
): CanvasDocument {
  return mapSide(doc, sideIndex, (s) => {
    const from = s.elements.findIndex((el) => el.id === elementId);
    if (from === -1) return s;
    const elements = [...s.elements];
    const [el] = elements.splice(from, 1);
    let to: number;
    if (delta === 'back') to = 0;
    else if (delta === 'front') to = elements.length;
    else to = Math.max(0, Math.min(elements.length, from + delta));
    elements.splice(to, 0, el);
    return { ...s, elements };
  });
}

export function addSide(doc: CanvasDocument, name = 'back'): CanvasDocument {
  return { ...doc, sides: [...doc.sides, { name, elements: [] }] };
}

export function removeSide(doc: CanvasDocument, sideIndex: number): CanvasDocument {
  if (doc.sides.length <= 1) return doc; // always keep at least one side
  return { ...doc, sides: doc.sides.filter((_, i) => i !== sideIndex) };
}

export function findElement(
  doc: CanvasDocument,
  sideIndex: number,
  elementId: string,
): CanvasElement | null {
  return doc.sides[sideIndex]?.elements.find((el) => el.id === elementId) ?? null;
}

// ---------------------------------------------------------------------------
// Validation mirror (D18) - keep PARITY with backend validate_canvas_doc.
// ---------------------------------------------------------------------------

export interface CanvasValidationContext {
  /** Scalar fact keys (the context's facts[].key). */
  factKeys: Set<string>;
}

function collectTokens(value: string | null | undefined, out: Set<string>): void {
  if (!value) return;
  const pattern = /\{\{\s*([\w.]+)\s*\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value)) !== null) out.add(match[1]);
}

function elementTokenValues(el: CanvasElement): string[] {
  if (el.type === 'text') return [el.content];
  if (el.type === 'image') return [el.src ?? ''];
  if (el.type === 'qr') return [el.data];
  if (el.type === 'customHtml') return [el.html];
  return [];
}

/**
 * Validate a canvas doc against its context. Returns a flat problem list ([] =
 * valid). Mirrors backend D18: ≥1 side + named, unique element ids within a
 * side, known merge fields, QR non-empty data, image src scheme. No hard
 * out-of-bounds fail (bleed = intentional overflow).
 */
export function validateCanvasDoc(
  doc: CanvasDocument,
  context: CanvasValidationContext,
  requiredFacts: string[] = [],
): string[] {
  const problems: string[] = [];
  if (!(doc.canvas.width > 0) || !(doc.canvas.height > 0))
    problems.push('Canvas width and height must be positive.');
  if (doc.sides.length === 0) problems.push('A badge needs at least one side.');

  const used = new Set<string>();
  doc.sides.forEach((side, i) => {
    if (!side.name.trim()) problems.push(`Side ${i + 1} needs a name.`);
    const seen = new Set<string>();
    for (const el of side.elements) {
      if (seen.has(el.id)) problems.push(`Side "${side.name}": duplicate element id "${el.id}".`);
      seen.add(el.id);
      if (el.type === 'qr' && !el.data.trim())
        problems.push(`QR element ${el.id}: add the data field.`);
      if (el.type === 'image' && el.src && !el.src.includes('{{')) {
        const scheme = el.src.includes(':') ? el.src.split(':', 1)[0].toLowerCase() : 'https';
        if (!['http', 'https', 'data'].includes(scheme))
          problems.push(`Image element ${el.id}: unsupported image URL scheme.`);
      }
      for (const value of elementTokenValues(el)) {
        const toks = new Set<string>();
        collectTokens(value, toks);
        Array.from(toks).forEach((tok) => {
          used.add(tok);
          if (context.factKeys.size && !context.factKeys.has(tok))
            problems.push(`Element ${el.id}: unknown merge field "{{${tok}}}".`);
        });
      }
    }
  });

  const missing = requiredFacts.filter((f) => !used.has(f));
  if (missing.length)
    problems.push(`Required merge field(s) missing: ${missing.map((m) => `{{${m}}}`).join(', ')}.`);

  return problems;
}
