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

function injectStylesheet(themeClass?: 'dark'): CSSStyleDeclaration {
  const style = document.createElement('style');
  style.textContent = `${forJsdom(configCss)}\n${forJsdom(foundryxCss)}`;
  document.head.appendChild(style);
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
  const steps: Array<[string, number]> = [
    ['--z-sticky-content', 5],
    ['--z-sticky-content-corner', 6],
    ['--z-header', 10],
    ['--z-sidebar', 20],
    ['--z-banner', 30],
    ['--z-modal', 50],
  ];

  it.each(steps)('defines %s as %i', (name, expected) => {
    const cs = injectStylesheet();
    expect(Number(cs.getPropertyValue(name).trim())).toBe(expected);
  });

  it('orders the scale: sticky-content < header < sidebar < banner < modal', () => {
    const cs = injectStylesheet();
    const n = (name: string) => Number(cs.getPropertyValue(name).trim());
    expect(n('--z-sticky-content')).toBeLessThan(n('--z-sticky-content-corner'));
    expect(n('--z-sticky-content-corner')).toBeLessThan(n('--z-header'));
    expect(n('--z-header')).toBeLessThan(n('--z-sidebar'));
    expect(n('--z-sidebar')).toBeLessThan(n('--z-banner'));
    expect(n('--z-banner')).toBeLessThan(n('--z-modal'));
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
    const offset = 'top-[var(--impersonation-banner-height,0px)]';
    expect(read('app/components/layouts/demo1/components/header.tsx')).toContain(offset);
    expect(read('app/components/layouts/demo1/components/sidebar.tsx')).toContain(`lg:${offset}`);
    // The banner is the one that SETS the offset - it must not hardcode a top-0
    // placement that would just stack on top of the header at the same layer.
    expect(read('components/impersonation/impersonation-banner.tsx')).toContain(
      '--impersonation-banner-height',
    );
  });

  it('leaves no ad-hoc z-[N] under app/** or components/**', () => {
    const offenders = walk(['app', 'components'])
      .filter((f) => /\.(tsx?|css)$/.test(f))
      .filter((f) => /\bz-\[\d+\]/.test(fs.readFileSync(f, 'utf8')));
    expect(offenders.map((f) => path.relative(root, f))).toEqual([]);
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
    expect(reduced).toMatch(/\[data-vaul-drawer\]\s*\{\s*transition-duration:\s*1ms\s*!important/);
    expect(reduced).toMatch(/\[class\*='transition-\['\]\s*\{\s*transition-duration:\s*1ms\s*!important/);
  });

  it('drops the backdrop filter and uses a 72% scrim under reduced transparency', () => {
    const reducedTransparencyBlock = reducedTransparency();
    expect(reducedTransparencyBlock).toContain('backdrop-filter: none');
    expect(reducedTransparencyBlock).toContain('[data-pinned]');
    expect(reducedTransparencyBlock).toContain('dialog-overlay');
    expect(reducedTransparencyBlock).toMatch(/--scrim:[^;]*72%/);
    expect(reducedTransparencyBlock).toMatch(/--material-regular:\s*var\(--background\)/);
  });

  it('raises borders/muted-foreground/material-edge under prefers-contrast: more (light and dark)', () => {
    const moreContrastBlock = moreContrast();
    expect(moreContrastBlock).toContain('backdrop-filter: none');
    expect(moreContrastBlock).toContain('[data-pinned]');
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

describe('AC-DLA-06 literal-sweep (motion/typography classes must resolve through tokens)', () => {
  const scanFiles = walk(['app', 'components']).filter((f) => /\.(tsx|ts)$/.test(f) && !f.endsWith('.test.ts') && !f.endsWith('.test.tsx'));
  const cssFiles = walk(['css']).filter((f) => f.endsWith('.css'));

  const rel = (f: string) => path.relative(root, f).split(path.sep).join('/');

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
});
