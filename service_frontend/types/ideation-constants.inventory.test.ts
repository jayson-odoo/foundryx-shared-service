/**
 * AC-94-55 (issue #94, ideation round 2) - the hardcoded status constants
 * inventory. Statuses now come from the statuses engine (`IdeaOut.statusId/
 * statusLabel/statusColor/statusIsArchived`, plan section 6); the frontend's
 * own hardcoded mirrors must be deleted, not just unused.
 *
 * TEST-FIRST (PRINCIPLES.md): `IDEA_STATUS_LABEL`, `IDEA_NEXT_STATUS` and
 * `IDEA_BOARD_COLUMNS` are still declared (and used) in `types/ideation.ts`
 * and several consumers today - this fails (non-empty hit list) until slice
 * S1 deletes them.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

// The exact three constants AC-94-55 names (grep -rn "A\|B\|C" service_frontend
// must return nothing once they're deleted).
const FORBIDDEN = ['IDEA_STATUS_LABEL', 'IDEA_NEXT_STATUS', 'IDEA_BOARD_COLUMNS'];

const SKIP_DIRS = new Set(['node_modules', '.next', '.git', 'coverage']);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (/\.(ts|tsx|js|jsx)$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

describe('ideation constants inventory (AC-94-55, issue #94)', () => {
  it('IDEA_STATUS_LABEL / IDEA_NEXT_STATUS / IDEA_BOARD_COLUMNS no longer exist anywhere in service_frontend', () => {
    const files = walk(repoRoot);
    const hits: string[] = [];
    for (const file of files) {
      if (path.resolve(file) === path.resolve(__filename)) continue; // this file names them by design
      const src = fs.readFileSync(file, 'utf8');
      for (const token of FORBIDDEN) {
        if (src.includes(token)) hits.push(`${path.relative(repoRoot, file)}: ${token}`);
      }
    }
    expect(hits).toEqual([]);
  });

  it('the IdeaStatus union type is gone - Idea.status becomes a plain string', () => {
    const src = fs.readFileSync(path.join(repoRoot, 'types', 'ideation.ts'), 'utf8');
    expect(src).not.toMatch(/export type IdeaStatus\b/);
    expect(src).toMatch(/status:\s*string;/);
  });
});
