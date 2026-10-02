/**
 * AC-DLA-11: `Badge` base is `rounded-full`, `md` = `h-6 px-2.5`, `sm` =
 * `h-5 px-2`; `appearance` is `light` (default) | `outline` (`ghost` removed);
 * `shape="circle"` unchanged for counts; every dark-mode `appearance="light"`
 * compound resolves DISTINCT bg/text tokens (the bug this AC fixes - both
 * used to read `-soft`, so a status pill was a solid block with invisible
 * text in dark mode). `status-badge.tsx` still renders the 6px dot.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge, BadgeDot, badgeVariants } from './badge';

const repoRoot = path.join(__dirname, '..', '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

function walk(dirs: string[]): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        visit(entryPath);
      } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
        out.push(entryPath);
      }
    }
  };
  for (const dir of dirs) visit(dir);
  return out;
}

describe('AC-DLA-11 Badge shape/appearance/status dot', () => {
  it('base is rounded-full', () => {
    const cls = badgeVariants({ variant: 'primary' });
    expect(cls).toContain('rounded-full');
  });

  it('md size is h-6 px-2.5, sm is h-5 px-2', () => {
    expect(badgeVariants({ size: 'md' })).toContain('h-6');
    expect(badgeVariants({ size: 'md' })).toMatch(/px-2\.5/);
    expect(badgeVariants({ size: 'sm' })).toContain('h-5');
    expect(badgeVariants({ size: 'sm' })).toMatch(/px-2\b/);
  });

  it('appearance accepts light (default) and outline; ghost is gone', () => {
    render(<Badge data-testid="b1">hi</Badge>);
    expect(screen.getByTestId('b1').className).not.toContain('bg-transparent');
    const src = read('components/ui/badge.tsx');
    expect(src).not.toMatch(/ghost:/);
    expect(src).toMatch(/appearance:\s*\{[^}]*light:/);
    expect(src).toMatch(/appearance:\s*\{[^}]*outline:/);
  });

  it('zero appearance="ghost" remains anywhere under app/** or components/**', () => {
    const offenders = walk(['app', 'components'])
      .filter((f) => !f.includes('badge.test.tsx'))
      .filter((f) => /appearance="ghost"/.test(read(f)))
      // button.tsx's own `appearance` variant (ghost is a valid Button appearance,
      // unrelated to Badge) is not part of this AC.
      .filter((f) => {
        const src = read(f);
        // Any hit that is a <Badge ...appearance="ghost" is a real offender; a
        // <Button appearance="ghost" is not.
        return /<Badge[^>]*appearance="ghost"/.test(src);
      });
    expect(offenders).toEqual([]);
  });

  it('shape="circle" keeps rounded-full (counts stay unchanged)', () => {
    expect(badgeVariants({ shape: 'circle' })).toContain('rounded-full');
  });

  it('BadgeDot is a 6px dot (size-1.5)', () => {
    render(<BadgeDot data-testid="dot" />);
    expect(screen.getByTestId('dot').className).toContain('size-1.5');
  });

  it('dark-mode appearance="light" compounds send bg and text to DIFFERENT tokens (the invisible-text bug)', () => {
    const src = read('components/ui/badge.tsx');
    // Every `light` compound's dark:bg-[...] and dark:text-[...] must reference
    // a different CSS custom property name, never the same `-soft` var for both.
    const lightBlockMatches = [...src.matchAll(/variant:\s*'(\w+)',\s*appearance:\s*'light',\s*className:\s*\n?\s*'([^']+)'/g)].filter(
      // `secondary` legitimately uses the semantic `bg-secondary`/
      // `text-secondary-foreground` tokens directly, not the `-soft`/`-accent`
      // custom-property pair this check is about.
      ([, variant]) => variant !== 'secondary',
    );
    expect(lightBlockMatches.length).toBeGreaterThan(0);
    for (const [, variant, className] of lightBlockMatches) {
      const darkBg = className.match(/dark:bg-\[var\((--color-[\w-]+)/);
      const darkText = className.match(/dark:text-\[var\((--color-[\w-]+)/);
      expect(darkBg, `${variant} dark:bg`).toBeTruthy();
      expect(darkText, `${variant} dark:text`).toBeTruthy();
      expect(darkText![1], `${variant} dark:text should not equal dark:bg (${darkBg![1]})`).not.toBe(darkBg![1]);
    }
  });
});
