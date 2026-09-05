/**
 * AC-DLA-09: `primitive-classes.ts` exports the shared class strings, and
 * every primitive that must carry `PRESSED_CLASS`/`PRESSED_TRANSFORM_CLASS`/
 * `COARSE_HIT_TARGET_CLASS` does - and no other primitive does. Source-scan
 * tests (this repo's established idiom for inventories, see
 * `css/design-tokens.test.ts`) rather than render tests: what is being
 * asserted is a property of each file's class string, not of one rendered
 * instance.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  COARSE_HIT_TARGET_CLASS,
  OVERLAY_CLASS,
  OVERLAY_CLASS_STATIC,
  PRESSED_CLASS,
  PRESSED_TRANSFORM_CLASS,
} from './primitive-classes';

const read = (rel: string) => fs.readFileSync(path.join(__dirname, '..', '..', rel), 'utf8');

describe('AC-DLA-09 primitive-classes exports', () => {
  it('exports OVERLAY_CLASS, OVERLAY_CLASS_STATIC, PRESSED_CLASS, PRESSED_TRANSFORM_CLASS, COARSE_HIT_TARGET_CLASS', () => {
    expect(typeof OVERLAY_CLASS).toBe('string');
    expect(typeof OVERLAY_CLASS_STATIC).toBe('string');
    expect(typeof PRESSED_CLASS).toBe('string');
    expect(typeof PRESSED_TRANSFORM_CLASS).toBe('string');
    expect(typeof COARSE_HIT_TARGET_CLASS).toBe('string');
  });

  it('OVERLAY_CLASS / OVERLAY_CLASS_STATIC use an 8px blur (backdrop-blur-sm), not backdrop-blur-md', () => {
    expect(OVERLAY_CLASS).toContain('backdrop-blur-sm');
    expect(OVERLAY_CLASS).not.toContain('backdrop-blur-md');
    expect(OVERLAY_CLASS_STATIC).toContain('backdrop-blur-sm');
    expect(OVERLAY_CLASS_STATIC).not.toContain('backdrop-blur-md');
  });

  it('PRESSED_CLASS transition list includes scale ALONGSIDE transform (fix round 1: Tailwind 4 compiles active:scale-[0.97] to the standalone scale property, not transform, so the press snapped without it)', () => {
    // Read the transition-[...] bracket itself and assert `scale` is one of
    // its comma-separated properties, not just a substring hit anywhere in
    // the class string (which could pass by accident via `active:scale-`).
    const bracket = PRESSED_CLASS.match(/transition-\[([^\]]+)\]/)?.[1] ?? '';
    const props = bracket.split(',');
    expect(props).toContain('transform');
    expect(props).toContain('scale');
    expect(props).toContain('color');
    expect(props).toContain('background-color');
    expect(props).toContain('border-color');
    expect(props).toContain('box-shadow');
    expect(PRESSED_CLASS).toContain('active:scale-[0.97]');
    expect(PRESSED_CLASS).toContain('motion-reduce:active:scale-100');
    expect(PRESSED_CLASS).toContain('duration-(--duration-fast)');
    expect(PRESSED_CLASS).toContain('ease-(--ease-standard)');
  });

  it('PRESSED_TRANSFORM_CLASS is transform-only (no colour transition) for roving-focus menu items', () => {
    expect(PRESSED_TRANSFORM_CLASS).toContain('transition-transform');
    expect(PRESSED_TRANSFORM_CLASS).not.toContain('color');
    expect(PRESSED_TRANSFORM_CLASS).not.toContain('background-color');
    expect(PRESSED_TRANSFORM_CLASS).not.toContain('border-color');
    expect(PRESSED_TRANSFORM_CLASS).not.toContain('box-shadow');
    expect(PRESSED_TRANSFORM_CLASS).toContain('active:scale-[0.97]');
    expect(PRESSED_TRANSFORM_CLASS).toContain('motion-reduce:active:scale-100');
    expect(PRESSED_TRANSFORM_CLASS).toContain('duration-(--duration-fast)');
    expect(PRESSED_TRANSFORM_CLASS).toContain('ease-(--ease-standard)');
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

  const carries = (file: string, token: string) => read(file).includes(token);

  it.each([
    ['components/ui/button.tsx', 'Button lg/md/icon'],
    ['components/ui/checkbox.tsx', 'Checkbox'],
    ['components/ui/switch.tsx', 'Switch'],
    ['components/ui/radio-group.tsx', 'RadioGroupItem'],
    ['components/ui/toggle.tsx', 'Toggle'],
    ['components/ui/tabs.tsx', 'TabsTrigger'],
  ])('%s imports/uses PRESSED_CLASS (%s)', (file) => {
    expect(carries(file, 'PRESSED_CLASS'), file).toBe(true);
  });

  it.each([
    ['components/ui/dropdown-menu.tsx', 'DropdownMenuItem'],
    ['components/ui/context-menu.tsx', 'ContextMenuItem'],
    ['components/ui/menubar.tsx', 'MenubarItem'],
  ])('%s imports/uses PRESSED_TRANSFORM_CLASS, not PRESSED_CLASS (%s)', (file) => {
    expect(carries(file, 'PRESSED_TRANSFORM_CLASS'), file).toBe(true);
    // `PRESSED_TRANSFORM_CLASS` does not contain the substring `PRESSED_CLASS`
    // by itself (there is `TRANSFORM_` in between), so this also asserts the
    // file never independently ALSO imports the colour-transitioning class.
    expect(carries(file, 'PRESSED_CLASS'), file).toBe(false);
  });

  it.each([
    ['components/ui/command.tsx', 'CommandItem - keyboard-driven, 100+/day'],
    ['components/ui/slider.tsx', 'SliderThumb - a drag is a hold'],
  ])('%s carries NEITHER press class (%s)', (file) => {
    expect(carries(file, 'PRESSED_CLASS'), file).toBe(false);
    expect(carries(file, 'PRESSED_TRANSFORM_CLASS'), file).toBe(false);
  });

  it.each([
    ['components/ui/button.tsx', 'Button lg/md/icon'],
    ['components/ui/checkbox.tsx', 'Checkbox'],
    ['components/ui/switch.tsx', 'Switch'],
    ['components/ui/radio-group.tsx', 'RadioGroupItem'],
  ])('%s imports/uses COARSE_HIT_TARGET_CLASS (%s)', (file) => {
    expect(carries(file, 'COARSE_HIT_TARGET_CLASS'), file).toBe(true);
  });

  it('button.tsx does NOT apply COARSE_HIT_TARGET_CLASS to the sm size (dense clusters)', () => {
    const src = read('components/ui/button.tsx');
    const smBlock = src.match(/sm:\s*'[^']*'/)?.[0] ?? '';
    expect(smBlock).not.toContain('COARSE_HIT_TARGET_CLASS');
  });
});
