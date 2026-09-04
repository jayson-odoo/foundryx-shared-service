/**
 * AC-DLA-09: `primitive-classes.ts` exports the shared class strings, and
 * every primitive that must carry `PRESSED_CLASS`/`COARSE_HIT_TARGET_CLASS`
 * does. Source-scan tests (this repo's established idiom for inventories,
 * see `css/design-tokens.test.ts`) rather than render tests: what is being
 * asserted is a property of each file's class string, not of one rendered
 * instance.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { COARSE_HIT_TARGET_CLASS, OVERLAY_CLASS, OVERLAY_CLASS_STATIC, PRESSED_CLASS } from './primitive-classes';

const read = (rel: string) => fs.readFileSync(path.join(__dirname, '..', '..', rel), 'utf8');

describe('AC-DLA-09 primitive-classes exports', () => {
  it('exports OVERLAY_CLASS, OVERLAY_CLASS_STATIC, PRESSED_CLASS, COARSE_HIT_TARGET_CLASS', () => {
    expect(typeof OVERLAY_CLASS).toBe('string');
    expect(typeof OVERLAY_CLASS_STATIC).toBe('string');
    expect(typeof PRESSED_CLASS).toBe('string');
    expect(typeof COARSE_HIT_TARGET_CLASS).toBe('string');
  });

  it('PRESSED_CLASS carries the transform/color/bg/border/shadow transition, the fast+standard tokens and the active scale', () => {
    expect(PRESSED_CLASS).toContain('transition-[transform,color,background-color,border-color,box-shadow]');
    expect(PRESSED_CLASS).toContain('active:scale-[0.97]');
    expect(PRESSED_CLASS).toContain('motion-reduce:active:scale-100');
    expect(PRESSED_CLASS).toContain('duration-(--duration-fast)');
    expect(PRESSED_CLASS).toContain('ease-(--ease-standard)');
  });

  it('COARSE_HIT_TARGET_CLASS is a 44px pointer-coarse pseudo-element target', () => {
    expect(COARSE_HIT_TARGET_CLASS).toContain('pointer-coarse:after:min-h-11');
    expect(COARSE_HIT_TARGET_CLASS).toContain('pointer-coarse:after:min-w-11');
    expect(COARSE_HIT_TARGET_CLASS).toContain('relative');
  });

  it('OVERLAY_CLASS_STATIC has no CSS fade-in/out keyframes (T3 drives its opacity)', () => {
    expect(OVERLAY_CLASS_STATIC).not.toContain('animate-in');
    expect(OVERLAY_CLASS_STATIC).not.toContain('animate-out');
    expect(OVERLAY_CLASS).toContain('data-[state=open]:animate-in');
  });

  const carriesPressedClass = (file: string) => read(file).includes('PRESSED_CLASS');
  const carriesCoarseHit = (file: string) => read(file).includes('COARSE_HIT_TARGET_CLASS');

  it.each([
    ['components/ui/button.tsx', 'Button lg/md/icon'],
    ['components/ui/checkbox.tsx', 'Checkbox'],
    ['components/ui/switch.tsx', 'Switch'],
    ['components/ui/radio-group.tsx', 'RadioGroupItem'],
    ['components/ui/toggle.tsx', 'Toggle'],
    ['components/ui/tabs.tsx', 'TabsTrigger'],
    ['components/ui/slider.tsx', 'SliderThumb'],
    ['components/ui/dropdown-menu.tsx', 'DropdownMenuItem'],
    ['components/ui/context-menu.tsx', 'ContextMenuItem'],
    ['components/ui/menubar.tsx', 'MenubarItem'],
    ['components/ui/command.tsx', 'CommandItem'],
  ])('%s imports/uses PRESSED_CLASS (%s)', (file) => {
    expect(carriesPressedClass(file), file).toBe(true);
  });

  it.each([
    ['components/ui/button.tsx', 'Button lg/md/icon'],
    ['components/ui/checkbox.tsx', 'Checkbox'],
    ['components/ui/switch.tsx', 'Switch'],
    ['components/ui/radio-group.tsx', 'RadioGroupItem'],
  ])('%s imports/uses COARSE_HIT_TARGET_CLASS (%s)', (file) => {
    expect(carriesCoarseHit(file), file).toBe(true);
  });

  it('button.tsx does NOT apply COARSE_HIT_TARGET_CLASS to the sm size (dense clusters)', () => {
    const src = read('components/ui/button.tsx');
    const smBlock = src.match(/sm:\s*'[^']*'/)?.[0] ?? '';
    expect(smBlock).not.toContain('COARSE_HIT_TARGET_CLASS');
  });
});
