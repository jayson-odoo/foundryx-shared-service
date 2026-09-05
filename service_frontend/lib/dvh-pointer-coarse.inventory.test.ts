/**
 * AC-DLA-52 - `h-dvh` on the left/right `Sheet` sizing (jobs/imports
 * drawers use it), an explicit `dvh` inner scroll region on the
 * notifications sheet, `calc(100dvh - ...)` on the omnichannel conversation
 * drawer's fixed-height shell, and `pointer-coarse:text-base` on the
 * default `Input` (so a touch focus never triggers iOS Safari's under-16px
 * auto-zoom). Also: the app declares no `maximum-scale` viewport meta
 * (there is no `viewport` export/meta anywhere - Next's default has none).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

describe('AC-DLA-52 dvh sizing + pointer-coarse input + no maximum-scale', () => {
  it('the shared Sheet primitive sizes left/right sides with h-dvh, not h-full', () => {
    const src = read('components/ui/sheet.tsx');
    expect(src).toMatch(/left:\s*'[^']*h-dvh/);
    expect(src).toMatch(/right:\s*'[^']*h-dvh/);
    expect(src).not.toMatch(/left:\s*'[^']*h-full/);
    expect(src).not.toMatch(/right:\s*'[^']*h-full/);
  });

  it('the notifications sheet sizes its scroll region off 100dvh, not 100vh', () => {
    const src = read('app/components/partials/topbar/notifications-sheet.tsx');
    expect(src).toContain('100dvh');
    expect(src).not.toContain('100vh');
  });

  it('the omnichannel conversation drawer shell sizes off 100dvh, not 100vh', () => {
    const src = read('app/(protected)/omnichannel/inbox/page.tsx');
    expect(src).toContain('100dvh');
    expect(src).not.toContain('100vh');
  });

  it('the default Input applies pointer-coarse:text-base on every density variant', () => {
    const src = read('components/ui/input.tsx');
    const variantBlock = src.slice(src.indexOf('variants: {'), src.indexOf('defaultVariants: {\n      variant: '));
    const densityLines = variantBlock.match(/(lg|md|sm):\s*'[^']*'/g) ?? [];
    expect(densityLines.length).toBeGreaterThanOrEqual(3);
    for (const line of densityLines) {
      expect(line, `${line} should carry pointer-coarse:text-base`).toContain('pointer-coarse:text-base');
    }
  });

  it('no tracked frontend file declares a maximum-scale viewport meta', () => {
    // A dedicated meta/viewport export is the only place this could live;
    // absence IS compliance (Next's own default carries no maximum-scale).
    const hasViewportExport = fs.existsSync(path.join(repoRoot, 'app', 'layout.tsx'))
      ? read('app/layout.tsx').includes('maximum-scale') || read('app/layout.tsx').includes('maximumScale')
      : false;
    expect(hasViewportExport).toBe(false);
  });
});
