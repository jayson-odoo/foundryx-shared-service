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

describe('AC-DLA-58 every raw <button element carries pressed feedback', () => {
  it('every raw <button element carries PRESSED_CLASS in its className (allowlist empty)', () => {
    const allowed = new Set(ALLOWLIST.map((f) => path.join(repoRoot, f)));
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      if (allowed.has(file)) continue;
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('<button')) continue;
      const rel = file.replace(repoRoot + path.sep, '');
      for (const tag of findRawButtonTags(src)) {
        if (!tag.includes('PRESSED_CLASS')) {
          offenders.push(`${rel}: ${tag.slice(0, 140).replace(/\s+/g, ' ')}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
