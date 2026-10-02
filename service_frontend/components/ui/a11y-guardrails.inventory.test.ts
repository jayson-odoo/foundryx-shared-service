/**
 * AC-DLA-59 - the accessibility guardrail inventory, checked against the
 * source tree (mirrors Sorento's `a11y-guardrails.inventory.test.ts`, ported
 * with this repo's own baseline and roster). What this asserts is a property
 * of the WHOLE tree ("no icon button ships without a name"), and a render
 * test can only speak for the component it mounted - a new icon-only
 * `<Button mode="icon">` added next month would pass every component test
 * and fail here.
 *
 * If you are adding an icon-only Button: pass `aria-label` (or an `sr-only`
 * child, or `aria-current` for a numbered pager button whose visible text
 * IS its name). If you are adding `role="content"` anywhere, don't - it is
 * not a valid ARIA role and `<main>` already carries the implicit one.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const ROOTS = ['app', 'components'];

/** Every `.tsx`/`.ts` under the scanned roots, tests excluded. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (
        (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts')) &&
        !entry.name.includes('.test.')
      ) {
        out.push(full);
      }
    }
  };
  for (const root of ROOTS) walk(path.join(repoRoot, root));
  return out;
}

/**
 * The opening tag and children of every `<Button ...>...</Button>` in `src`,
 * brace/quote depth tracked so `className={cn('a', x && 'b')}` does not end
 * the tag early.
 */
function findButtons(src: string): { tag: string; children: string }[] {
  const out: { tag: string; children: string }[] = [];
  const opener = /<Button(?![A-Za-z])/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(src))) {
    let i = m.index;
    let depth = 0;
    let quote: string | null = null;
    let tagEnd = -1;
    let selfClosing = false;
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
        selfClosing = src[i - 1] === '/';
        break;
      }
      i += 1;
    }
    if (tagEnd === -1) continue;
    const tag = src.slice(m.index, tagEnd);
    let children = '';
    if (!selfClosing) {
      let nestDepth = 1;
      let j = tagEnd;
      const openRe = /<Button(?![A-Za-z])/g;
      const closeRe = /<\/Button>/g;
      while (nestDepth > 0) {
        openRe.lastIndex = j;
        closeRe.lastIndex = j;
        const om = openRe.exec(src);
        const cm = closeRe.exec(src);
        if (!cm) break;
        if (om && om.index < cm.index) {
          nestDepth += 1;
          j = om.index + om[0].length;
        } else {
          nestDepth -= 1;
          j = cm.index + cm[0].length;
          if (nestDepth === 0) {
            children = src.slice(tagEnd, cm.index);
          }
        }
      }
    }
    out.push({ tag, children });
  }
  return out;
}

/** Genuine future exceptions get a name + reason here, never a silent add. */
const ICON_BUTTON_EXEMPT_PATHS: string[] = [];

describe('AC-DLA-59 icon-button labels', () => {
  it('every mode="icon" / size="icon" Button has an accessible name (allowlist empty)', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const rel = file.replace(repoRoot + path.sep, '').split(path.sep).join('/');
      if (ICON_BUTTON_EXEMPT_PATHS.some((p) => rel.startsWith(p))) continue;
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('<Button')) continue;
      for (const { tag, children } of findButtons(src)) {
        if (!/mode="icon"|size="icon"/.test(tag)) continue;
        if (/aria-label|aria-labelledby/.test(tag)) continue;
        if (children.includes('sr-only')) continue;
        // asChild delegates the rendered element (and its aria-label) to its
        // single child - Radix Slot merges the Button's own props onto it.
        if (tag.includes('asChild') && children.includes('aria-label')) continue;
        // A numbered pager button renders its own page number as visible
        // text - the number itself is the accessible name; aria-current
        // marks the active one instead of duplicating it.
        if (tag.includes('aria-current')) continue;
        offenders.push(`${rel}: ${tag.slice(0, 120).replace(/\s+/g, ' ')}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('AC-DLA-59 role="content" removed everywhere', () => {
  it('no file sets the non-standard role="content" (main already has an implicit role)', () => {
    const pattern = new RegExp(['role', '="content"'].join(''));
    const offenders = sourceFiles()
      .filter((f) => pattern.test(fs.readFileSync(f, 'utf8')))
      .map((f) => f.replace(repoRoot + path.sep, ''));
    expect(offenders).toEqual([]);
  });
});

describe('AC-DLA-59 skip link', () => {
  it('the protected shell renders a skip link to #main, and #main exists', () => {
    const layout = fs.readFileSync(
      path.join(repoRoot, 'app/components/layouts/demo1/layout.tsx'),
      'utf8',
    );
    expect(layout).toMatch(/href="#main"/);
    expect(layout).toMatch(/id="main"/);
  });
});

describe('AC-DLA-59 focus rings on outline-none/outline-hidden sites', () => {
  // Each site the T7 sweep fixed (had NO ring anywhere in the file, or the
  // ring was deliberately zeroed out with no replacement), pinned so a
  // later refactor cannot drop it silently.
  const RING_FIXED: { file: string; needle: string | RegExp }[] = [
    { file: 'components/ui/slider.tsx', needle: 'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2' },
  ];

  it('each fixed site still carries its ring', () => {
    for (const { file, needle } of RING_FIXED) {
      const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
      if (typeof needle === 'string') expect(src, file).toContain(needle);
      else expect(src, file).toMatch(needle);
    }
  });

  it('the search dialog input no longer force-zeroes its ring (relies on the Input primitive default)', () => {
    const src = fs.readFileSync(
      path.join(repoRoot, 'app/components/partials/dialogs/search/search-dialog.tsx'),
      'utf8',
    );
    expect(src).not.toMatch(/ring-0!/);
    expect(src).not.toMatch(/outline-none!/);
  });
});
