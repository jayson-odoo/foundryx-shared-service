/**
 * AC-DLA-58 - every raw `<button` element under `app/(protected)` and
 * `components/platform` either IS a `Button` (which already carries
 * `PRESSED_CLASS` unconditionally, `button.tsx`) or carries the shared
 * `PRESSED_CLASS` string (from `primitive-classes`) somewhere in its own
 * className expression, threaded via `cn(...)`.
 *
 * Checked PER ELEMENT (T7 fix round 1 - the original file-level check only
 * proved a file imported `Button` SOMEWHERE, which let a raw `<button>` sit
 * unpressed in a file that also happened to use `Button` for something
 * else; 60 such elements across 25 files were found and fixed this round).
 * The element's opening tag is extracted brace/quote-depth aware (mirrors
 * `a11y-guardrails.inventory.test.ts`'s `findButtons`, adapted to lowercase
 * `<button`), so a multi-line `className={cn(...)}` expression is captured
 * whole.
 *
 * Baseline (T7 sweep): 17 files fixed at file granularity, then a further 25
 * files / 60 elements fixed at element granularity (fix round 1). The
 * allowlist starts and stays empty; a future genuine exception needs a
 * named reason here, not a silent add.
 *
 * T8 (AC-DLA-67 animation review item 3) - a `cursor-grab` element is a
 * DRAG HANDLE, not a press target: a drag is a HOLD (dnd-kit's own drag
 * transform runs for the whole gesture), so `PRESSED_CLASS`'s
 * `active:scale-[0.97]` would sit scaled down for the entire hold and
 * compound with dnd-kit's transform. Exempted by CLASS CONTENT
 * (`cursor-grab` in the element's own className), not a per-file allowlist
 * - the second `it` below proves the exemption actually matches real drag
 * handles rather than being a silent no-op.
 *
 * T8 fix round 1 - `cursor-grab` alone is too loose a signal (any button
 * could carry the CLASS without actually being a wired-up dnd-kit handle,
 * e.g. a copy-paste leftover), so the exemption is narrowed to
 * `isCursorGrabDragHandle(tag)`: `cursor-grab` in the className AND either
 * `{...listeners}` (dnd-kit's `useDraggable` spread) or
 * `aria-roledescription` (dnd-kit's own a11y convention for a drag handle)
 * on the SAME opening tag. A `cursor-grab` button with neither is not
 * proven to be a real drag handle and still must carry `PRESSED_CLASS` -
 * the fourth `it` below pins that.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const ALLOWLIST: string[] = [];

function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app/(protected)', 'components/platform'];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) {
        out.push(full);
      }
    }
  };
  for (const root of roots) walk(path.join(repoRoot, root));
  return out;
}

/**
 * The opening tag of every raw `<button ...>` in `src`, brace/quote depth
 * tracked so a multi-line `className={cn('a', x && 'b')}` does not end the
 * tag early. Excludes `<Button`/`<ButtonGroup` etc (capital B, a different
 * component) via the negative lookahead on the next char after `button`.
 */
function findRawButtonTags(src: string): string[] {
  const out: string[] = [];
  const opener = /<button(?![A-Za-z0-9_-])/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(src))) {
    let i = m.index;
    let depth = 0;
    let quote: string | null = null;
    let tagEnd = -1;
    while (i < src.length) {
      const c = src[i];
      if (quote) {
        if (c === '\\') i += 1;
        else if (c === quote) quote = null;
      } else if (c === '"' || c === "'" || c === '`') {
        quote = c;
      } else if (c === '{') {
        depth += 1;
      } else if (c === '}') {
        depth -= 1;
      } else if (c === '>' && depth === 0) {
        tagEnd = i + 1;
        break;
      }
      i += 1;
    }
    if (tagEnd === -1) continue;
    out.push(src.slice(m.index, tagEnd));
  }
  return out;
}

/**
 * `cursor-grab` alone is not proof of a wired-up dnd-kit drag handle - it
 * needs `{...listeners}` (the `useDraggable` spread) or
 * `aria-roledescription` (dnd-kit's own drag-handle a11y convention) on the
 * SAME opening tag too. A `cursor-grab` button with neither is treated as an
 * ordinary press target and still must carry `PRESSED_CLASS`.
 */
function isCursorGrabDragHandle(tag: string): boolean {
  return tag.includes('cursor-grab') && (tag.includes('{...listeners}') || tag.includes('aria-roledescription'));
}

describe('AC-DLA-58 every raw <button element carries pressed feedback', () => {
  it('every raw <button element carries PRESSED_CLASS in its className, or is a cursor-grab drag handle (allowlist empty)', () => {
    const allowed = new Set(ALLOWLIST.map((f) => path.join(repoRoot, f)));
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      if (allowed.has(file)) continue;
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('<button')) continue;
      const rel = file.replace(repoRoot + path.sep, '');
      for (const tag of findRawButtonTags(src)) {
        if (isCursorGrabDragHandle(tag)) continue; // a hold, not a press - see file doc comment
        if (!tag.includes('PRESSED_CLASS')) {
          offenders.push(`${rel}: ${tag.slice(0, 140).replace(/\s+/g, ' ')}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('the cursor-grab drag-handle exemption matches real elements, not a silent no-op', () => {
    let dragHandleCount = 0;
    for (const file of sourceFiles()) {
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('<button')) continue;
      for (const tag of findRawButtonTags(src)) {
        if (isCursorGrabDragHandle(tag)) dragHandleCount += 1;
      }
    }
    expect(dragHandleCount).toBeGreaterThan(0);
  });

  it('a cursor-grab button WITHOUT listeners/aria-roledescription is still required to carry PRESSED_CLASS', () => {
    // A `cursor-grab` class alone is not proof of a real dnd-kit drag handle
    // - it could be a copy-paste leftover on an ordinary press target. Such
    // a tag must NOT be exempted (isCursorGrabDragHandle === false) and must
    // still fail the requirement when PRESSED_CLASS is absent.
    const plainCursorGrab = '<button type="button" className="cursor-grab rounded p-1" onClick={onClick}>';
    expect(isCursorGrabDragHandle(plainCursorGrab)).toBe(false);

    const src = `function C() { return (\n  ${plainCursorGrab}\n    <GripVertical />\n  </button>\n); }`;
    const offenders = findRawButtonTags(src).filter(
      (tag) => !isCursorGrabDragHandle(tag) && !tag.includes('PRESSED_CLASS'),
    );
    expect(offenders).toEqual([plainCursorGrab]);

    // Sanity: a genuine listeners-carrying drag handle IS exempted.
    const realHandle =
      '<button type="button" aria-label="Drag" className="cursor-grab" {...listeners} {...attributes}>';
    expect(isCursorGrabDragHandle(realHandle)).toBe(true);
  });

  it('the reorder-only drag handles (no click affordance) carry no PRESSED_CLASS', () => {
    // A pure reorder handle (aria-label "Drag ...", no onClick that performs
    // an action of its own) must not compound dnd-kit's live drag transform
    // with PRESSED_CLASS's active:scale for the whole hold. A palette item
    // (click-to-add AND drag-to-add, e.g. email-editor/palette.tsx) is a
    // real press target too and legitimately keeps PRESSED_CLASS - this
    // check is scoped to the named reorder-handle files, not every
    // cursor-grab element in the app.
    const REORDER_HANDLE_FILES = [
      'components/platform/resource-list/resource-list.tsx',
      'components/platform/form-builder/canvas.tsx',
      'components/platform/form-builder/settings-panel.tsx',
      'components/platform/email-editor/canvas.tsx',
    ];
    const offenders: string[] = [];
    for (const rel of REORDER_HANDLE_FILES) {
      const full = path.join(repoRoot, rel);
      const src = fs.readFileSync(full, 'utf8');
      for (const tag of findRawButtonTags(src)) {
        if (tag.includes('cursor-grab') && tag.includes('PRESSED_CLASS')) {
          offenders.push(`${rel}: ${tag.slice(0, 140).replace(/\s+/g, ' ')}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
