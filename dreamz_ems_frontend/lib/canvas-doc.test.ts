import { describe, expect, it } from 'vitest';
import {
  addElement,
  addSide,
  clampBox,
  clampElementPatch,
  createBlankBadgeDoc,
  createCanvasElement,
  findElement,
  mmToUnit,
  removeElement,
  removeSide,
  reorderElement,
  roundForUnit,
  unitToMm,
  updateCanvas,
  updateElement,
  validateCanvasDoc,
} from '@/lib/canvas-doc';
import type { CanvasDocument, CanvasQrElement, CanvasTextElement } from '@/types/templates';

const ctx = { factKeys: new Set(['attendeeName', 'role', 'company', 'ticketCode']) };

function docWith(...types: Array<'text' | 'image' | 'shape' | 'qr'>): CanvasDocument {
  let doc = createBlankBadgeDoc();
  for (const t of types) doc = addElement(doc, 0, createCanvasElement(t, doc.canvas));
  return doc;
}

describe('canvas-doc factories + mutations', () => {
  it('blank badge = 86×54 landscape, one front side', () => {
    const doc = createBlankBadgeDoc();
    expect(doc.canvas.width).toBe(86);
    expect(doc.canvas.height).toBe(54);
    expect(doc.canvas.orientation).toBe('landscape');
    expect(doc.sides).toHaveLength(1);
    expect(doc.sides[0].name).toBe('front');
  });

  it('createCanvasElement centres the element and sets type defaults', () => {
    const doc = createBlankBadgeDoc();
    const text = createCanvasElement('text', doc.canvas) as CanvasTextElement;
    expect(text.type).toBe('text');
    expect(text.fontFamily).toBe('Inter');
    // centred horizontally: x + w/2 ≈ width/2
    expect(text.x + text.w / 2).toBeCloseTo(doc.canvas.width / 2, 1);
    const qr = createCanvasElement('qr', doc.canvas) as CanvasQrElement;
    expect(qr.ecLevel).toBe('M');
    expect(qr.w).toBe(qr.h); // square
  });

  it('add / update / remove element', () => {
    let doc = docWith('text');
    const id = doc.sides[0].elements[0].id;
    doc = updateElement(doc, 0, id, { x: 12 } as Partial<CanvasTextElement>);
    expect(findElement(doc, 0, id)?.x).toBe(12);
    doc = removeElement(doc, 0, id);
    expect(doc.sides[0].elements).toHaveLength(0);
  });

  it('reorderElement moves z (array order)', () => {
    let doc = docWith('text', 'shape', 'qr');
    const [a] = doc.sides[0].elements;
    doc = reorderElement(doc, 0, a.id, 'front');
    expect(doc.sides[0].elements[2].id).toBe(a.id);
    doc = reorderElement(doc, 0, a.id, 'back');
    expect(doc.sides[0].elements[0].id).toBe(a.id);
    doc = reorderElement(doc, 0, a.id, 1);
    expect(doc.sides[0].elements[1].id).toBe(a.id);
  });

  it('add / remove side (always keeps ≥1)', () => {
    let doc = addSide(createBlankBadgeDoc(), 'back');
    expect(doc.sides).toHaveLength(2);
    doc = removeSide(doc, 1);
    expect(doc.sides).toHaveLength(1);
    doc = removeSide(doc, 0); // refuse to drop the last side
    expect(doc.sides).toHaveLength(1);
  });

  it('updateCanvas patches the size block', () => {
    const doc = updateCanvas(createBlankBadgeDoc(), { unit: 'in', width: 100 });
    expect(doc.canvas.unit).toBe('in');
    expect(doc.canvas.width).toBe(100);
  });
});

describe('containment — no element exceeds the canvas', () => {
  const canvas = createBlankBadgeDoc().canvas; // 86×54

  it('clampBox keeps a box inside the page', () => {
    expect(clampBox(canvas, -10, -5, 40, 10)).toEqual({ x: 0, y: 0, w: 40, h: 10 });
    expect(clampBox(canvas, 80, 50, 40, 10)).toEqual({ x: 46, y: 44, w: 40, h: 10 });
  });

  it('clampBox caps size to the canvas', () => {
    expect(clampBox(canvas, 0, 0, 999, 999)).toEqual({ x: 0, y: 0, w: 86, h: 54 });
  });

  it('clampElementPatch only touches geometry patches', () => {
    const el = createCanvasElement('text', canvas);
    const moved = clampElementPatch(canvas, el, { x: 200 });
    expect((moved as { x: number }).x).toBe(canvas.width - el.w);
    // a non-geometry patch passes through untouched
    expect(clampElementPatch(canvas, el, { color: '#fff' } as never)).toEqual({ color: '#fff' });
  });
});

describe('unit conversion (display ⇄ mm)', () => {
  it('mm is identity', () => {
    expect(mmToUnit(50, 'mm')).toBe(50);
    expect(unitToMm(50, 'mm')).toBe(50);
  });
  it('inches round-trip', () => {
    expect(mmToUnit(25.4, 'in')).toBeCloseTo(1, 5);
    expect(unitToMm(1, 'in')).toBeCloseTo(25.4, 5);
  });
  it('px @96dpi round-trip', () => {
    expect(mmToUnit(25.4, 'px')).toBeCloseTo(96, 3);
    expect(unitToMm(96, 'px')).toBeCloseTo(25.4, 5);
  });
  it('roundForUnit uses 3dp for inches, 1dp otherwise', () => {
    expect(roundForUnit(1.23456, 'in')).toBe(1.235);
    expect(roundForUnit(1.23456, 'mm')).toBe(1.2);
  });
});

describe('validateCanvasDoc mirror (D18)', () => {
  it('valid badge → no problems', () => {
    let doc = createBlankBadgeDoc();
    const text = createCanvasElement('text', doc.canvas) as CanvasTextElement;
    text.content = '{{attendeeName}}';
    doc = addElement(doc, 0, text);
    expect(validateCanvasDoc(doc, ctx, ['attendeeName'])).toEqual([]);
  });

  it('unknown merge field flagged', () => {
    let doc = createBlankBadgeDoc();
    const text = createCanvasElement('text', doc.canvas) as CanvasTextElement;
    text.content = '{{nope}}';
    doc = addElement(doc, 0, text);
    expect(validateCanvasDoc(doc, ctx).some((p) => p.includes('unknown merge field'))).toBe(true);
  });

  it('empty QR data flagged', () => {
    let doc = createBlankBadgeDoc();
    doc = addElement(doc, 0, createCanvasElement('qr', doc.canvas));
    expect(validateCanvasDoc(doc, ctx).some((p) => p.includes('QR element'))).toBe(true);
  });

  it('required fact missing flagged', () => {
    let doc = createBlankBadgeDoc();
    const qr = createCanvasElement('qr', doc.canvas) as CanvasQrElement;
    qr.data = '{{ticketCode}}';
    doc = addElement(doc, 0, qr);
    expect(validateCanvasDoc(doc, ctx, ['attendeeName']).some((p) => p.includes('Required'))).toBe(true);
  });

  it('duplicate element id flagged', () => {
    const doc = createBlankBadgeDoc();
    const a = createCanvasElement('text', doc.canvas) as CanvasTextElement;
    a.content = '{{role}}';
    const b = { ...a }; // same id
    doc.sides[0].elements.push(a, b);
    expect(validateCanvasDoc(doc, ctx).some((p) => p.includes('duplicate element id'))).toBe(true);
  });

  it('token image src is allowed (scheme-checked post-merge)', () => {
    let doc = createBlankBadgeDoc();
    const img = createCanvasElement('image', doc.canvas);
    if (img.type === 'image') img.src = '{{logoUrl}}';
    doc = addElement(doc, 0, img);
    const probs = validateCanvasDoc(doc, { factKeys: new Set(['logoUrl']) });
    expect(probs.filter((p) => p.includes('scheme'))).toEqual([]);
  });
});
