/**
 * T1 tokens/CSS/preferences guardrail - AC-DLA-01 .. AC-DLA-07 of
 * documentation/plans/sprint-4/23-design-language-alignment-acceptance-criteria.md.
 *
 * jsdom does not run Tailwind, so a raw `@theme { --x: y }` block (Tailwind's special
 * at-rule with no selector) never lands on any element's computed style - a real
 * browser would not resolve it either without Tailwind's build step. To still get a
 * "computed-style test resolves each" (the AC's own words) rather than a text-grep,
 * every CSS file below is injected into a real `<style>` tag with `@theme`/`@theme
 * inline` REWRITTEN to `:root` first, so `getComputedStyle` sees the declarations at
 * the same specificity Tailwind would have registered them at. `getPropertyValue` on
 * a custom property returns the raw cascaded text (it does not itself follow nested
 * `var()` references) - `resolveVar` below walks that chain by hand.
 */
import { describe, expect, it } from 'vitest';
import fs from 'fs';
import path from 'path';

const root = path.resolve(__dirname, '..');
const read = (rel: string) => fs.readFileSync(path.join(root, rel), 'utf8');

const configCss = read('css/config.reui.css');
const foundryxCss = read('css/foundryx-tokens.css');
const stylesCss = read('css/styles.css');

/** Rewrites Tailwind's selector-less `@theme` / `@theme inline` blocks to `:root`
 *  so a vanilla CSS parser (jsdom included) attributes the declarations to the
 *  document root instead of silently dropping an at-rule it does not understand. */
function forJsdom(css: string): string {
  return css.replace(/@theme(\s+inline)?\s*\{/g, ':root {');
}

// Injected once per theme (not once per test/describe): every describe block below
// calls this many times, and jsdom's getComputedStyle re-evaluates the cascade on
// every call anyway - appending a duplicate <style> tag per call bought nothing but
// slower CI and O(n) accumulated tags. One <style> per theme is the real cost.
let styleInjected = false;
function injectStylesheet(themeClass?: 'dark'): CSSStyleDeclaration {
  if (!styleInjected) {
    const style = document.createElement('style');
    style.textContent = `${forJsdom(configCss)}\n${forJsdom(foundryxCss)}`;
    document.head.appendChild(style);
    styleInjected = true;
  }
  document.documentElement.classList.toggle('dark', themeClass === 'dark');
  return getComputedStyle(document.documentElement);
}

/** Follows a `var(--x)` chain to its literal value (colour, length, keyword, ...). */
function resolveVar(name: string, cs: CSSStyleDeclaration, seen = new Set<string>()): string {
  if (seen.has(name)) throw new Error(`circular var() reference at ${name}`);
  seen.add(name);
  const value = cs.getPropertyValue(name).trim();
  const ref = /^var\((--[a-z0-9-]+)(?:\s*,.*)?\)$/i.exec(value);
  return ref ? resolveVar(ref[1], cs, seen) : value;
}

/** Body of the first `{...}` that follows `selector`, brace-balanced so nested
 *  at-rules (e.g. a media query around further rules) survive intact. */
function block(css: string, selector: string): string {
  const at = css.indexOf(selector);
  if (at === -1) throw new Error(`selector not found: ${selector}`);
  const open = css.indexOf('{', at);
  if (open === -1) throw new Error(`no block for: ${selector}`);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced block for: ${selector}`);
}

/** Linear-light sRGB channels of a `#rgb`/`#rrggbb` colour (our tokens are hex). */
function linearRgb(value: string): [number, number, number] {
  const hex = /^#([0-9a-f]{3,6})$/i.exec(value.trim());
  if (!hex) throw new Error(`unsupported colour for contrast check: ${value}`);
  const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join('') : hex[1];
  return [0, 2, 4].map((i) => {
    const channel = parseInt(digits.slice(i, i + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
}

function luminance(value: string): number {
  const [r, g, b] = linearRgb(value);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe('AC-DLA-01 motion tokens', () => {
  it.each(['light', 'dark'] as const)('defines --ease-standard and the three durations (%s)', (theme) => {
    const cs = injectStylesheet(theme === 'dark' ? 'dark' : undefined);
    expect(resolveVar('--ease-standard', cs)).toMatch(/^cubic-bezier\(/);
    expect(resolveVar('--duration-fast', cs)).toBe('150ms');
    expect(resolveVar('--duration-base', cs)).toBe('200ms');
    expect(resolveVar('--duration-slow', cs)).toBe('300ms');
  });

  it('points the Tailwind default transition timing/duration at the house curve', () => {
    const cs = injectStylesheet();
    expect(resolveVar('--default-transition-timing-function', cs)).toMatch(/^cubic-bezier\(/);
    expect(resolveVar('--default-transition-duration', cs)).toBe('150ms');
  });
});

describe('AC-DLA-02 material tokens', () => {
  it.each(['light', 'dark'] as const)('defines the material/scrim tokens (%s)', (theme) => {
    const cs = injectStylesheet(theme === 'dark' ? 'dark' : undefined);
    const regular = cs.getPropertyValue('--material-regular').trim();
    const thick = cs.getPropertyValue('--material-thick').trim();
    const scrim = cs.getPropertyValue('--scrim').trim();
    expect(regular).toContain(theme === 'dark' ? '76%' : '72%');
    expect(thick).toContain(theme === 'dark' ? '90%' : '88%');
    expect(scrim).toContain(theme === 'dark' ? '62%' : '50%');
    expect(cs.getPropertyValue('--material-blur').trim()).toBe('24px');
    expect(cs.getPropertyValue('--material-edge').trim()).toBeTruthy();
  });

  it('ships the material utilities in styles.css', () => {
    for (const name of ['material-regular', 'material-thick', 'material-edge']) {
      expect(stylesCss).toContain(`@utility ${name}`);
    }
  });

  it('dresses the header in material-regular and the sidebar in material-thick', () => {
    const header = read('app/components/layouts/demo1/components/header.tsx');
    const sidebar = read('app/components/layouts/demo1/components/sidebar.tsx');
    expect(header).toContain('material-regular');
    expect(header).toContain('material-edge');
    expect(header).not.toContain('bg-background');
    expect(sidebar).toContain('material-thick');
    expect(sidebar).not.toContain('bg-background');
  });
});

describe('AC-DLA-03 named z-scale', () => {
  // --z-banner sits ABOVE --z-modal (fix round 1 finding 2) - PAINT ORDER ONLY: the
  // banner is never covered by an overlay's scrim while a dialog/sheet/drawer is
  // open over the page. This does NOT guarantee clickability - a Radix overlay's
  // `pointer-events: none` on the body can still swallow a click on the banner even
  // though it paints on top (tracked BL-SS-050, T1 fix round 3 finding 3).
  // --z-sticky-content-corner was dropped (T1 fix round 3 finding 10) - it had no
  // consumer (no cell pinned on both axes exists yet); re-add it, registered here,
  // if one ever does.
  // --z-sticky-header (T2 fix round 2) is the sticky <thead> + the mobile-pinned
  // HEADER cell - one step above --z-sticky-content (pinned BODY cells) so a
  // pinned column slides UNDER the header when the grid scrolls, not over it.
  const steps: Array<[string, number]> = [
    ['--z-sticky-content', 5],
    ['--z-sticky-header', 6],
    ['--z-header', 10],
    ['--z-sidebar', 20],
    ['--z-modal', 50],
    ['--z-banner', 60],
  ];

  it.each(steps)('defines %s as %i', (name, expected) => {
    const cs = injectStylesheet();
    expect(Number(cs.getPropertyValue(name).trim())).toBe(expected);
  });

  it('orders the scale: sticky-content < sticky-header < header < sidebar < modal < banner', () => {
    const cs = injectStylesheet();
    const n = (name: string) => Number(cs.getPropertyValue(name).trim());
    expect(n('--z-sticky-content')).toBeLessThan(n('--z-sticky-header'));
    expect(n('--z-sticky-header')).toBeLessThan(n('--z-header'));
    expect(n('--z-header')).toBeLessThan(n('--z-sidebar'));
    expect(n('--z-sidebar')).toBeLessThan(n('--z-modal'));
    expect(n('--z-modal')).toBeLessThan(n('--z-banner'));
  });

  it('references the named steps in the shell instead of an ad-hoc z-[N]', () => {
    const shell: Record<string, string> = {
      'app/components/layouts/demo1/components/header.tsx': 'z-(--z-header)',
      'app/components/layouts/demo1/components/sidebar.tsx': 'z-(--z-sidebar)',
      'components/impersonation/impersonation-banner.tsx': 'z-(--z-banner)',
    };
    for (const [file, token] of Object.entries(shell)) {
      expect(read(file), file).toContain(token);
    }
  });

  it('offsets the header and sidebar below the impersonation banner instead of being covered by it', () => {
    const offset = 'top-[var(--shell-top-offset,0px)]';
    expect(read('app/components/layouts/demo1/components/header.tsx')).toContain(offset);
    expect(read('app/components/layouts/demo1/components/sidebar.tsx')).toContain(`lg:${offset}`);
    // The banner is the one that SETS the offset - it must not hardcode a top-0
    // placement that would just stack on top of the header at the same layer.
    expect(read('components/impersonation/impersonation-banner.tsx')).toContain('--shell-top-offset');
    // A hardcoded constant undercounts the real (wrapping) rendered height (fix round
    // 1 finding 1) - the banner has to MEASURE itself.
    expect(read('components/impersonation/impersonation-banner.tsx')).toContain('ResizeObserver');
    expect(read('components/impersonation/impersonation-banner.tsx')).not.toMatch(/BANNER_HEIGHT/);
  });

  it('carries --shell-top-offset into the wrapper padding-top and the settings sticky nav, on top of --header-height', () => {
    const demo1Css = read('css/demos/demo1.css');
    const offsetFormula = 'calc(var(--header-height) + var(--shell-top-offset, 0px))';
    // Both wrapper rules (unpinned sidebar, sidebar-fixed) - the header alone
    // dropping while the wrapper stayed at a bare --header-height hid the page title
    // under it (fix round 1 finding 1).
    expect((demo1Css.match(new RegExp(offsetFormula.replace(/[()+]/g, '\\$&'), 'g')) ?? []).length).toBeGreaterThanOrEqual(2);
    const settingsSidebar = read('app/(protected)/account/home/settings-sidebar/content.tsx');
    expect(settingsSidebar).toContain('calc(var(--header-height)+var(--shell-top-offset,0px)+1rem)');
  });

  /**
   * T1 fix round 2: the sidebar box itself already shrinks with the banner
   * (lg:top-(--shell-top-offset) lg:bottom-0), but the menu scroller kept a
   * `100vh`-relative cap (`calc(100vh-5.5rem)`) instead of being bounded by the
   * REMAINING height inside that box - with the banner expanded, the scroller's cap
   * stayed a fixed viewport fraction while the box shrank underneath it, so the
   * last ~7px of the final nav item sat past the sidebar's real bottom edge,
   * unreachable at max scroll. The fix bounds the scroller with flex (h-full/
   * max-h-full through a flex-1 min-h-0 ancestor), never a 100vh calc.
   */
  it('bounds the sidebar menu scroller by the remaining flex height, not a 100vh calc', () => {
    const sidebarTsx = read('app/components/layouts/demo1/components/sidebar.tsx');
    expect(sidebarTsx).toMatch(/overflow-hidden[^"'`]*\bflex-1\b[^"'`]*\bmin-h-0\b/);
    const sidebarMenuTsx = read('app/components/layouts/demo1/components/sidebar-menu.tsx');
    expect(sidebarMenuTsx).not.toMatch(/max-h-\[calc\(100vh/);
    expect(sidebarMenuTsx).toMatch(/\blg:h-full\b/);
    expect(sidebarMenuTsx).toMatch(/\blg:max-h-full\b/);
  });

  it('leaves no ad-hoc z-[N] under app/** or components/**', () => {
    const offenders = walk(['app', 'components'])
      .filter((f) => /\.(tsx?|css)$/.test(f))
      .filter((f) => /\bz-\[\d+\]/.test(fs.readFileSync(f, 'utf8')));
    expect(offenders.map((f) => path.relative(root, f))).toEqual([]);
  });

  /**
   * T1 fix round 1 finding 7 widens the guard past the Tailwind `z-[N]` class
   * vocabulary to a raw `zIndex:` inline style (navigation-menu.tsx's indicator used
   * exactly this before this fix-round, specifically to dodge the `z-[N]` ban - an
   * escape hatch that needed closing too). The five that remain all compute the
   * value from RUNTIME drag/pin state (`isDragging ? 1 : 0`), which a static
   * Tailwind class cannot express - a real exception, not an oversight, so they are
   * an explicit allowlist rather than a silent pass.
   */
  const zIndexInlineStyleAllowlist = new Set([
    'components/ui/data-grid-table.tsx',
    'components/ui/data-grid-table-dnd.tsx',
    'components/ui/data-grid-table-dnd-rows.tsx',
    'components/ui/avatar-group.tsx',
  ]);

  it('leaves no zIndex: inline style outside the runtime-drag/-pin allowlist', () => {
    const offenders = walk(['app', 'components'])
      .filter((f) => /\.tsx?$/.test(f))
      .filter((f) => !zIndexInlineStyleAllowlist.has(rel(f)))
      .filter((f) => /\bzIndex\s*:/.test(fs.readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('documents the remaining bare numeric z-<N> utilities as a baseline (Sorento parity - allowed, not banned)', () => {
    const hits = walk(['app', 'components'])
      .filter((f) => /\.tsx?$/.test(f))
      .flatMap((f) => fs.readFileSync(f, 'utf8').match(/\bz-\d+\b/g) ?? []);
    // A specific count would be brittle busywork to maintain by hand on every
    // unrelated PR; a wide ceiling still catches an accidental mass-revert.
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.length).toBeLessThan(120);
  });

  /**
   * T1 fix round 3 finding 4: bare numeric `z-<N>` utilities are BANNED under
   * `app/**` and `components/platform/**` outside an explicit allowlist - the
   * broad "documents...as a baseline" ceiling test above stays the Sorento-parity
   * check for the WHOLE tree (components/ui/** included, still just tolerated under
   * a wide count); this stricter pass targets the two trees where a hand-rolled
   * sticky/overlay surface tends to reach for `z-10` instead of the named scale
   * (the bug three of these findings fixed). The Metronic `demo2`-`demo10` layouts
   * are exempt (dead code, D8 - T7 deletes them wholesale), matching AC-DLA-06's own
   * exemption. The allowlist starts as exactly the genuine baseline found by this
   * sweep - every entry computes its stacking order from something the shell's named
   * steps don't model (an avatar-group hover-to-front, a canvas drag handle's local
   * z, a context-menu/inspector portal) - not a silent grandfather clause; a NEW
   * hand-rolled z-index anywhere else in these two trees now fails the build.
   */
  const isExemptDemoLayoutForZ = (f: string) => /app\/components\/layouts\/demo(10|[2-9])\//.test(f);

  const zNumericAllowlist = new Set([
    // app/**
    'app/components/partials/common/avatar-input.tsx',
    'app/components/partials/common/avatar-group.tsx',
    // components/platform/**
    'components/platform/document-drive/cursor-menu.tsx',
    'components/platform/overflow-pills/overflow-pills.tsx',
    'components/platform/resource-list/resource-list.tsx',
    'components/platform/email-editor/canvas.tsx',
    'components/platform/email-editor/block-view.tsx',
    'components/platform/workflow-canvas/workflow-canvas.tsx',
    'components/platform/status-engine/status-table.tsx',
    'components/platform/status-engine/entity-flow.tsx',
  ]);

  it('bans bare z-<N> under app/** and components/platform/** outside the recorded baseline allowlist', () => {
    const offenders = walk(['app', 'components/platform'])
      .filter((f) => /\.tsx?$/.test(f))
      .filter((f) => !isExemptDemoLayoutForZ(rel(f)))
      .filter((f) => !zNumericAllowlist.has(rel(f)))
      .filter((f) => /\bz-\d+\b/.test(fs.readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('records the app/**+components/platform/** z-<N> baseline as exactly 10 files (T1 fix round 3)', () => {
    expect(zNumericAllowlist.size).toBe(10);
  });
});

describe('AC-DLA-04 type scale, optical sizing and title leading', () => {
  const scale: Array<[string, string, string | null]> = [
    ['2xl', '-0.02em', '1.15'],
    ['xl', '-0.015em', '1.2'],
    ['lg', '-0.01em', '1.3'],
    ['base', '0em', '1.5'],
    ['xs', '0.01em', null],
    ['2xs', '0.02em', null],
    ['2sm', '0em', null],
  ];

  it.each(scale)('bakes tracking (and leading) into text-%s', (size, tracking, leading) => {
    const cs = injectStylesheet();
    expect(cs.getPropertyValue(`--text-${size}--letter-spacing`).trim()).toBe(tracking);
    if (leading) expect(cs.getPropertyValue(`--text-${size}--line-height`).trim()).toBe(leading);
  });

  it('keeps --font-sans on Inter and --font-heading on Poppins (brand, unchanged)', () => {
    expect(foundryxCss).toMatch(/--font-sans:\s*var\(--font-inter\)/);
    expect(foundryxCss).toMatch(/--font-heading:\s*var\(--font-poppins\)/);
    const layout = read('app/layout.tsx');
    expect(layout).toContain("variable: '--font-inter'");
    expect(layout).toContain("variable: '--font-poppins'");
  });

  it('turns optical sizing on for the body', () => {
    expect(stylesCss).toMatch(/body\s*\{[^}]*font-optical-sizing:\s*auto/);
  });

  it.each([
    ['components/ui/card.tsx', 'CardTitle'],
    ['components/ui/dialog.tsx', 'DialogTitle'],
    ['components/ui/alert-dialog.tsx', 'AlertDialogTitle'],
    ['components/ui/sheet.tsx', 'SheetTitle'],
  ])('gives %s (%s) leading-tight tracking-normal', (file, component) => {
    expect(read(file), `${file} (${component})`).toContain('leading-tight tracking-normal');
  });
});

describe('AC-DLA-05 accessibility preference blocks', () => {
  const reducedMotion = () => block(stylesCss, '@media (prefers-reduced-motion: reduce)');
  const reducedTransparency = () => block(stylesCss, '@media (prefers-reduced-transparency: reduce)');
  const moreContrast = () => block(stylesCss, '@media (prefers-contrast: more)');

  it('turns overlay slides and zooms into 150ms fades', () => {
    const reduced = reducedMotion();
    expect(reduced).toContain("[data-slot$='-content']");
    expect(reduced).toContain('[data-radix-popper-content-wrapper]');
    for (const v of [
      '--tw-enter-translate-x',
      '--tw-enter-translate-y',
      '--tw-exit-translate-x',
      '--tw-exit-translate-y',
    ]) {
      expect(reduced).toMatch(new RegExp(`${v}:\\s*0`));
    }
    expect(reduced).toMatch(/--tw-enter-scale:\s*1/);
    expect(reduced).toMatch(/--tw-exit-scale:\s*1/);
    expect(reduced).toMatch(/animation-duration:\s*150ms/);
    expect(reduced).toMatch(/transition-duration:\s*150ms/);
  });

  it('excludes dialog-content/sheet-content from the blanket 150ms transition', () => {
    const reduced = reducedMotion();
    const selector = /^[^{]*\{/.exec(reduced)?.[0] ?? '';
    expect(selector).toMatch(
      /\[data-slot\$='-content'\]:not\(\[data-slot='dialog-content'\]\):not\(\[data-slot='sheet-content'\]\)/,
    );
  });

  it('gives every -content slot the reduced-motion rule to bite on', () => {
    for (const file of ['dialog.tsx', 'alert-dialog.tsx', 'sheet.tsx']) {
      expect(read(`components/ui/${file}`), file).toMatch(/data-slot="[a-z-]+-content"/);
    }
  });

  it('stops pulse and bounce but leaves spinners spinning', () => {
    const reduced = reducedMotion();
    expect(reduced).toContain('.animate-pulse');
    expect(reduced).toContain('.animate-bounce');
    expect(reduced).not.toContain('.animate-spin');
  });

  it('stops the demo1 shell CSS transitions and collapses vaul/arbitrary transitions to 1ms', () => {
    const reduced = reducedMotion();
    expect(reduced).toMatch(/\.demo1 \.sidebar,\s*\n?\s*\.demo1 \.wrapper,\s*\n?\s*\.demo1 \.header/);
    expect(reduced).toMatch(/\.demo1[\s\S]*\{\s*transition:\s*none\s*!important/);
    // T3 fix round 1 finding 5 (BLOCKER 3): vaul opens/closes via a CSS
    // ANIMATION, not a transition - both `[data-vaul-drawer]` AND
    // `[data-vaul-overlay]` need `animation-duration` reset alongside
    // `transition-duration`, or a reduced-motion reader still gets the full
    // 500ms slide.
    expect(reduced).toMatch(
      /\[data-vaul-drawer\],\s*\n?\s*\[data-vaul-overlay\]\s*\{\s*transition-duration:\s*1ms\s*!important;\s*\n?\s*animation-duration:\s*1ms\s*!important/,
    );
    expect(reduced).toMatch(/\[class\*='transition-\['\]\s*\{\s*transition-duration:\s*1ms\s*!important/);
  });

  it('pins the normal-motion vaul drawer/overlay animation to --duration-slow, outside the reduced-motion query', () => {
    expect(stylesCss).toMatch(
      /\[data-vaul-drawer\],\s*\n?\s*\[data-vaul-overlay\]\s*\{\s*animation-duration:\s*var\(--duration-slow\)\s*!important/,
    );
  });

  // T1 fix round 1 finding 6: reduced-transparency and prefers-contrast: more used to
  // carry two independent copies of the same material/scrim/pinned flattening (and
  // prefers-contrast: more was MISSING the overlay scrim rule reduced-transparency
  // had). One merged `@media (prefers-reduced-transparency: reduce), (prefers-
  // contrast: more)` query now carries the shared flattening; `moreContrast()` below
  // (searching for the bare `@media (prefers-contrast: more)` selector, which the
  // merged query's text does not contain as a standalone string) resolves to the
  // SEPARATE, contrast-only delta block.
  it('merges reduced-transparency and prefers-contrast: more into one shared flattening query', () => {
    const merged = reducedTransparency();
    expect(merged).toContain('backdrop-filter: none');
    expect(merged).toContain('[data-pinned]');
    expect(merged).toContain('dialog-overlay');
    expect(merged).toMatch(/--scrim:[^;]*72%/);
    expect(merged).toMatch(/--material-regular:\s*var\(--background\)/);
    // The overlay scrim rule now applies under EITHER preference, not just
    // reduced-transparency - the gap prefers-contrast: more had before this fix.
    expect(merged).toMatch(/background-color:\s*var\(--scrim\)\s*!important/);
    const mediaSelector = stylesCss.slice(
      stylesCss.indexOf('@media (prefers-reduced-transparency: reduce)'),
      stylesCss.indexOf('{', stylesCss.indexOf('@media (prefers-reduced-transparency: reduce)')),
    );
    expect(mediaSelector).toContain('(prefers-contrast: more)');
  });

  it('raises borders/muted-foreground/material-edge under prefers-contrast: more ONLY (light and dark)', () => {
    const moreContrastBlock = moreContrast();
    // The shared flattening (backdrop-filter/pinned/scrim) lives in the merged query
    // above now - this block carries only the deltas reduced-transparency does not.
    expect(moreContrastBlock).not.toContain('backdrop-filter');
    expect(moreContrastBlock).not.toContain('[data-pinned]');
    expect(moreContrastBlock).toMatch(/--border:/);
    expect(moreContrastBlock).toMatch(/--input:/);
    expect(moreContrastBlock).toMatch(/--muted-foreground:/);
    expect(moreContrastBlock).toMatch(/--material-edge:/);
    // Both the flat :root block and a nested .dark block are present.
    expect(moreContrastBlock).toMatch(/\.dark\s*\{[^}]*--border:/);
  });
});

/** Files under the given repo-relative directories, recursively (Node 22 `recursive`). */
function walk(dirs: string[]): string[] {
  const out: string[] = [];
  for (const dir of dirs) {
    const abs = path.join(root, dir);
    if (!fs.existsSync(abs)) continue;
    const entries = fs.readdirSync(abs, { recursive: true, withFileTypes: true }) as fs.Dirent[];
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      // Node's recursive readdirSync exposes `parentPath` (22+) / `path` (older) as the
      // directory the entry was found in - join defensively across both.
      const parentPath = (entry as unknown as { parentPath?: string; path?: string }).parentPath ?? entry.path;
      out.push(path.join(parentPath, entry.name));
    }
  }
  return out;
}

/** Repo-root-relative, forward-slashed path (used by every inventory sweep below). */
const rel = (f: string) => path.relative(root, f).split(path.sep).join('/');

describe('AC-DLA-06 literal-sweep (motion/typography classes must resolve through tokens)', () => {
  const scanFiles = walk(['app', 'components']).filter((f) => /\.(tsx|ts)$/.test(f) && !f.endsWith('.test.ts') && !f.endsWith('.test.tsx'));
  const cssFiles = walk(['css']).filter((f) => f.endsWith('.css'));

  it('leaves no raw cubic-bezier( outside config.reui.css', () => {
    const offenders = [...scanFiles, ...cssFiles]
      .filter((f) => rel(f) !== 'css/config.reui.css')
      .filter((f) => /cubic-bezier\(/.test(fs.readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('leaves no transition-all', () => {
    const offenders = scanFiles.filter((f) => /\btransition-all\b/.test(fs.readFileSync(f, 'utf8'))).map(rel);
    expect(offenders).toEqual([]);
  });

  /**
   * Literal `duration-<N>` allowlist. Two categories only:
   *  - `input-otp.tsx` - the OTP caret is an `animate-caret-blink` PERIOD, not a
   *    transition, so it is not one of the three motion steps.
   *  - `github-button.tsx` - one of the 16 dead decor components (D10); T3 deletes
   *    the whole file, so it is not worth token-sweeping first.
   */
  const durationAllowlist = new Set(['components/ui/input-otp.tsx', 'components/ui/github-button.tsx']);

  it('leaves no literal duration-<N> outside the allowlist', () => {
    const offenders = scanFiles
      .filter((f) => !durationAllowlist.has(rel(f)))
      .filter((f) => /\bduration-\d+\b/.test(fs.readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('leaves no bespoke ease-in / ease-in-out (every one found was on an entering/exiting surface)', () => {
    const offenders = scanFiles.filter((f) => /\bease-in(-out)?\b/.test(fs.readFileSync(f, 'utf8'))).map(rel);
    expect(offenders).toEqual([]);
  });

  /**
   * `text-[Npx]` allowlist: the Metronic `demo2`-`demo10` layouts under
   * `app/components/layouts/` are unmounted dead demo (D8) that T7 deletes
   * wholesale - not worth a token sweep first. `demo1` (mounted) is NOT exempt.
   */
  const isExemptDemoLayout = (f: string) => /app\/components\/layouts\/demo(10|[2-9])\//.test(f);

  it('leaves no text-[Npx] outside the demo2-10 exemption', () => {
    const offenders = scanFiles
      .filter((f) => !isExemptDemoLayout(rel(f)))
      .filter((f) => /text-\[\d+px\]/.test(fs.readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });
});

describe('AC-DLA-07 semantic ink contrast', () => {
  const semantic = ['mono', 'success', 'info', 'warning'];

  it.each(semantic)('keeps --%s and its foreground defined in :root and .dark', (name) => {
    const light = injectStylesheet();
    const dark = injectStylesheet('dark');
    expect(resolveVar(`--${name}`, light)).toBeTruthy();
    expect(resolveVar(`--${name}-foreground`, light)).toBeTruthy();
    expect(resolveVar(`--${name}`, dark)).toBeTruthy();
    expect(resolveVar(`--${name}-foreground`, dark)).toBeTruthy();
  });

  it.each(semantic)('pairs --%s with its foreground at 4.5:1 or better (light)', (name) => {
    const cs = injectStylesheet();
    const base = resolveVar(`--${name}`, cs);
    const fg = resolveVar(`--${name}-foreground`, cs);
    expect(contrast(base, fg)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(semantic)('pairs --%s with its foreground at 4.5:1 or better (dark)', (name) => {
    const cs = injectStylesheet('dark');
    const base = resolveVar(`--${name}`, cs);
    const fg = resolveVar(`--${name}-foreground`, cs);
    expect(contrast(base, fg)).toBeGreaterThanOrEqual(4.5);
  });

  // Sorento's own comment on this token block states the DOUBLE constraint: a
  // semantic ink has to clear 4.5:1 both (a) as a fill's ink against its foreground
  // (asserted above) AND (b) used directly as text ON --background (a bare
  // `text-success` toast/body-copy use, not paired with any foreground at all). The
  // ORIGINAL raw brand hue failed (b) in light mode at 3.49:1 - rather than point
  // --success/--info/--warning at a DIFFERENT primitive (-active/-accent, which
  // would disconnect the tenant Branding controls from what the semantic var
  // renders - T1 fix round 3), the --foundryx-success/-info/-warning primitives
  // THEMSELVES are darkened in :root/light until the raw hue clears both (a) and
  // (b) at once (see css/foundryx-tokens.css's Layer 1/2 comments for the hex +
  // ratio history).
  it.each(semantic)('clears 4.5:1 as ink directly on --background (light, constraint b)', (name) => {
    const cs = injectStylesheet();
    const base = resolveVar(`--${name}`, cs);
    const bg = resolveVar('--background', cs);
    expect(contrast(base, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(semantic)('clears 4.5:1 as ink directly on --background (dark, constraint b)', (name) => {
    const cs = injectStylesheet('dark');
    const base = resolveVar(`--${name}`, cs);
    const bg = resolveVar('--background', cs);
    expect(contrast(base, bg)).toBeGreaterThanOrEqual(4.5);
  });

  // alert.tsx's `appearance="light"` icon sits on the TINTED `-soft` background, not
  // on a solid fill - that is a different pairing than "foreground on the ink" above,
  // and using --success-foreground there (white/black, a fill-ink colour) was
  // measured at 1.13:1 on --success-soft (nearly invisible) before this fix. The icon
  // now reads off --success-accent/-info-accent/-warning-accent directly.
  const alertHues = ['success', 'info', 'warning'];

  it.each(alertHues)("alert.tsx light-appearance icon (--%s-accent) reads on its -soft tint (light)", (name) => {
    const cs = injectStylesheet();
    const accent = resolveVar(`--${name}-accent`, cs);
    const soft = resolveVar(`--${name}-soft`, cs);
    expect(contrast(accent, soft)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(alertHues)("alert.tsx light-appearance icon (--%s-accent) reads on its -soft tint (dark)", (name) => {
    const cs = injectStylesheet('dark');
    const accent = resolveVar(`--${name}-accent`, cs);
    const soft = resolveVar(`--${name}-soft`, cs);
    expect(contrast(accent, soft)).toBeGreaterThanOrEqual(4.5);
  });

  // badge.tsx's DEFAULT (solid, non-"light") success/warning/info variant is
  // `bg-<hue>-accent text-<hue>-foreground` (components/ui/badge.tsx) - verify that
  // pairing directly rather than assuming it inherits constraint (a)'s pass (that one
  // paired the foreground against --success itself, i.e. the base primitive, not
  // -accent - a separate, darker step).
  it.each(alertHues)('badge.tsx default appearance (-foreground on -accent) clears 4.5:1 (light)', (name) => {
    const cs = injectStylesheet();
    const accent = resolveVar(`--${name}-accent`, cs);
    const fg = resolveVar(`--${name}-foreground`, cs);
    expect(contrast(accent, fg)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(alertHues)('badge.tsx default appearance (-foreground on -accent) clears 4.5:1 (dark)', (name) => {
    const cs = injectStylesheet('dark');
    const accent = resolveVar(`--${name}-accent`, cs);
    const fg = resolveVar(`--${name}-foreground`, cs);
    expect(contrast(accent, fg)).toBeGreaterThanOrEqual(4.5);
  });

  it('sends alert.tsx light-appearance AND mono+icon compounds to -accent, not -foreground (a fill-ink colour, not a tint-safe one)', () => {
    const alertSrc = read('components/ui/alert.tsx');
    for (const name of alertHues) {
      // The three appearance="light" compound variants, plus the "mono" variant's
      // icon compounds (T1 fix round 3 finding 7 - these used -foreground before,
      // which is the wrong role here: -foreground is fill ink for text ON a solid
      // hue-coloured surface, not an accent tint for an icon sitting on an
      // unrelated mono/neutral surface).
      const accentVar = `var(--color-${name}-accent,`;
      const occurrences = alertSrc.split(`[&_[data-slot=alert-icon]]:text-[${accentVar}`).length - 1;
      expect(occurrences, `${name} icon should use -accent in both its light-appearance and mono compounds`).toBe(2);
      expect(alertSrc).not.toContain(`[&_[data-slot=alert-icon]]:text-[var(--color-${name}-foreground,`);
    }
  });
});
