/**
 * AC-DLA-16: `tooltip.tsx` is a bare `Root` (no auto-wrapped provider); exactly
 * ONE `TooltipProvider` (`delayDuration={700} skipDelayDuration={300}`) is
 * mounted, in `providers/tooltips-provider.tsx`; `theme-provider.tsx` no
 * longer wraps one; tooltip content animates opacity only (no `zoom-in-95`).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

describe('AC-DLA-16 one TooltipProvider, 700/300, bare Root, opacity-only content', () => {
  it('tooltip.tsx Tooltip is a bare Root - no internal TooltipProvider wrap', () => {
    const src = read('components/ui/tooltip.tsx');
    const rootFn = src.match(/function Tooltip\(([\s\S]*?)\n\}/)?.[0] ?? '';
    expect(rootFn).not.toContain('<TooltipProvider>');
    expect(rootFn).toContain('TooltipPrimitive.Root');
  });

  it('providers/tooltips-provider.tsx sets delayDuration 700 and skipDelayDuration 300', () => {
    const src = read('providers/tooltips-provider.tsx');
    expect(src).toContain('delayDuration={700}');
    expect(src).toContain('skipDelayDuration={300}');
  });

  it('theme-provider.tsx no longer wraps a TooltipProvider', () => {
    const src = read('providers/theme-provider.tsx');
    expect(src).not.toContain('TooltipProvider');
  });

  it('tooltip content animates opacity only - no zoom-in-95/zoom-out-95, uses duration-fast', () => {
    const src = read('components/ui/tooltip.tsx');
    expect(src).not.toContain('zoom-in-95');
    expect(src).not.toContain('zoom-out-95');
    expect(src).toContain('duration-(--duration-fast)');
  });
});
