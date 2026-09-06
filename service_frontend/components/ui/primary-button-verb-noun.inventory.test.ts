/**
 * AC-DLA-35 (fix round 1): primary buttons read verb + noun ("Save user",
 * "Create role") - no bare "Submit" / "Save" / "OK". A source-level scan: a
 * `<Button` element whose JSX text child, on its own line, is EXACTLY
 * "Save", "Submit" or "OK" (case-sensitive - the literal word, not a
 * substring like "Saved" or "Save & resubmit"). The allowlist starts empty;
 * a genuine future exception is added here with a reason, never silently.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');

function walk(dirs: string[]): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        // The Metronic demo2-10 layouts are dead demo code (D8), never routed.
        if (/^demo(?:[2-9]|10)$/.test(entry.name)) continue;
        visit(entryPath);
      } else if (/\.tsx$/.test(entry.name) && !entry.name.includes('.test.')) {
        out.push(entryPath);
      }
    }
  };
  for (const dir of dirs) visit(dir);
  return out;
}

const BANNED = /^(Save|Submit|OK)$/;

/** Files with a known-bare "Save"/"Submit"/"OK" Button - starts empty. */
const ALLOWLIST: string[] = [];

function findBareOffenders(src: string): number[] {
  const lines = src.split('\n');
  const offenders: number[] = [];
  let insideButton = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!insideButton) {
      if (/<Button\b/.test(line) && !/\/>\s*$/.test(line)) {
        insideButton = true;
      }
      continue;
    }
    if (BANNED.test(line.trim())) {
      offenders.push(i + 1);
    }
    if (/<\/Button>/.test(line)) {
      insideButton = false;
    }
  }
  return offenders;
}

describe('AC-DLA-35 no bare Save/Submit/OK primary button', () => {
  it('every <Button whose text child is exactly Save/Submit/OK reads verb + noun instead', () => {
    const dirs = ['app/(protected)', 'components/platform', 'components/common'];
    const offenders: string[] = [];
    for (const file of walk(dirs)) {
      if (ALLOWLIST.includes(file)) continue;
      const src = fs.readFileSync(path.join(repoRoot, file), 'utf8');
      for (const line of findBareOffenders(src)) {
        offenders.push(`${file}:${line}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('the allowlist starts empty', () => {
    expect(ALLOWLIST).toEqual([]);
  });
});
