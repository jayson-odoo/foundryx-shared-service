/**
 * T5 fix round 2, S6: `ENTITY_NOUNS` (`lib/deferred-verb.ts`) covered only 12
 * of the registered `entityType`s - the rest leaked the raw registry key
 * into a commit toast ("Ideation_idea deleted."). This inventory walks every
 * `ResourceAction.deferred = { actionKey, entityType }` config in the app
 * (grep-based, mirrors `confirm-carve-outs.inventory.test.ts`) and asserts
 * every distinct `entityType` used has an `ENTITY_NOUNS` entry - a new
 * deferred action with no noun mapping fails this test, not silently.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { ENTITY_NOUNS } from './deferred-verb';

const repoRoot = path.join(__dirname, '..');

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
      } else if (
        (/\.tsx$/.test(entry.name) || /\.ts$/.test(entry.name)) &&
        !entry.name.includes('.test.')
      ) {
        out.push(entryPath);
      }
    }
  };
  for (const dir of dirs) visit(dir);
  return out;
}

/** Brace-match every `deferred: { ... }` object literal (mirrors the
 * carve-outs inventory's `extractConfirmBlocks`) so a nested `entityType`
 * elsewhere in the file (e.g. an unrelated prop) is never mistaken for one. */
function extractDeferredBlocks(src: string): string[] {
  const blocks: string[] = [];
  const opener = /deferred:\s*\{/g;
  let match: RegExpExecArray | null;
  while ((match = opener.exec(src)) !== null) {
    const openBraceIndex = match.index + match[0].length - 1;
    let depth = 0;
    let i = openBraceIndex;
    for (; i < src.length; i += 1) {
      if (src[i] === '{') depth += 1;
      else if (src[i] === '}') {
        depth -= 1;
        if (depth === 0) {
          i += 1;
          break;
        }
      }
    }
    blocks.push(src.slice(openBraceIndex, i));
  }
  return blocks;
}

function collectDeclaredEntityTypes(): Set<string> {
  const types = new Set<string>();
  for (const file of walk(['app', 'components'])) {
    const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
    for (const block of extractDeferredBlocks(src)) {
      const m = block.match(/entityType:\s*['"]([a-zA-Z_]+)['"]/);
      if (m) types.add(m[1]);
    }
  }
  return types;
}

describe('S6: every deferred-action entityType has an ENTITY_NOUNS entry', () => {
  it('finds at least the currently-registered entity types (the walk itself is not vacuous)', () => {
    const types = collectDeclaredEntityTypes();
    expect(types.size).toBeGreaterThan(20);
    expect(types.has('user')).toBe(true);
    expect(types.has('tenant_module')).toBe(true);
  });

  it('every entityType used by a `deferred:` config has an ENTITY_NOUNS entry', () => {
    const types = collectDeclaredEntityTypes();
    const missing = Array.from(types).filter((t) => !ENTITY_NOUNS[t]);
    expect(missing).toEqual([]);
  });
});
