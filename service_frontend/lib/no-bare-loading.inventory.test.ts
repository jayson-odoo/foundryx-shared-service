// @vitest-environment node
/**
 * AC-DLA-49 - zero files render the bare string `Loading...`/`Loading…`.
 * A "loading" state gets a `Skeleton` shape (sized by context) or a bare
 * spinner icon - never a spinner+text pill or a placeholder string, which
 * is exactly what this test used to find (`ContentLoader`, `ScreenLoader`,
 * a `DataGrid` overlay, several "Load more" buttons, several document-drive
 * panels, a few `SearchSelect` placeholders).
 *
 * A single `git grep` over TRACKED files - gitignored build output never
 * decides the verdict (same rationale as this repo's other retirement-
 * guard test). This file and its own test doc/comments necessarily discuss
 * the banned string, so it excludes itself.
 */
import { describe, expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';

const THIS_FILE = 'service_frontend/lib/no-bare-loading.inventory.test.ts';

function repoRoot(): string {
  return execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
}

function grepHits(pattern: string): string[] {
  try {
    // -P = Perl-compatible, for the \b word boundary - a plain substring
    // match on "loading" would false-positive on "Uploading…" (it CONTAINS
    // "loading" as a substring).
    const out = execFileSync(
      'git',
      ['grep', '-P', '-Iiln', pattern, '--', 'service_frontend'],
      { cwd: repoRoot(), encoding: 'utf8' },
    );
    return out.split('\n').filter(Boolean);
  } catch (err: unknown) {
    const e = err as { status?: number; stdout?: Buffer | string };
    if (e.status === 1) return []; // no matches
    throw err;
  }
}

describe('AC-DLA-49 no bare "loading" + ellipsis strings', () => {
  it('zero tracked frontend files (outside this guard) contain the literal string', () => {
    const hits = new Set(grepHits('\\bLoading(\\.\\.\\.|…)'));
    hits.delete(THIS_FILE);
    expect([...hits]).toEqual([]);
  });
});
