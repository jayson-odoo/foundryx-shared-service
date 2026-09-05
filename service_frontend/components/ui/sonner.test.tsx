/**
 * AC-DLA-17: `sonner.tsx` `Toaster` renders `position="top-center"` and
 * `closeButton`; `providers/query-provider.tsx` drops its per-call `position`.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

describe('AC-DLA-17 Toaster top-center + closeButton', () => {
  it('sonner.tsx renders position="top-center" and closeButton', () => {
    const src = read('components/ui/sonner.tsx');
    expect(src).toMatch(/<Sonner[\s\S]*?position="top-center"/);
    expect(src).toMatch(/<Sonner[\s\S]*?closeButton/);
  });

  it('query-provider.tsx no longer passes a per-call position to toast.custom', () => {
    const src = read('providers/query-provider.tsx');
    expect(src).not.toContain("position: 'top-center'");
    expect(src).not.toMatch(/toast\.custom\([\s\S]*?position:/);
  });
});
