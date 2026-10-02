/**
 * AC-DLA-25 - the 16 decor components deleted in T3 must never come back,
 * and `framer-motion` must never become a direct product import again
 * (`motion` is THE animation dependency; `framer-motion` is only `motion`'s
 * own internal transitive dependency, never imported directly).
 *
 * Reads the filesystem rather than importing - importing a deleted module
 * would fail the TEST FILE at compile time (a false pass for the wrong
 * reason: "the module doesn't resolve" looks identical whether it was
 * never created or correctly deleted). Checking `existsSync` plus a
 * grep-style content scan for `from 'framer-motion'` is what actually
 * proves the deletion, and proves it stays deleted if someone re-adds one.
 */
import { existsSync, readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

const UI_DIR = join(__dirname);

const DELETED_DECOR_COMPONENTS = [
  'marquee',
  'text-reveal',
  'shimmering-text',
  'sliding-number',
  'counting-number',
  'gradient-background',
  'hover-background',
  'grid-background',
  'stepper',
  'word-rotate',
  'typing-text',
  'avatar-group',
  'video-text',
  'github-button',
  'skeleton-with-pattern',
  'svg-text',
] as const;

describe('AC-DLA-25 - deleted decor components stay deleted', () => {
  it.each(DELETED_DECOR_COMPONENTS)('components/ui/%s.tsx does not exist', (name) => {
    expect(existsSync(join(UI_DIR, `${name}.tsx`))).toBe(false);
  });

  it('lists exactly the 16 deleted names (this test itself cannot silently shrink)', () => {
    expect(DELETED_DECOR_COMPONENTS).toHaveLength(16);
  });

  it('no components/ui/*.tsx file imports framer-motion directly', () => {
    const FRAMER_IMPORT = new RegExp(['from', " ['\"]", 'framer-motion', "['\"]"].join(''));
    const offenders: string[] = [];
    for (const entry of readdirSync(UI_DIR)) {
      if (entry === 'deleted-motion-components.guard.test.ts') continue;
      if (!entry.endsWith('.tsx') && !entry.endsWith('.ts')) continue;
      const contents = readFileSync(join(UI_DIR, entry), 'utf8');
      if (FRAMER_IMPORT.test(contents)) {
        offenders.push(entry);
      }
    }
    expect(offenders).toEqual([]);
  });
});
