/**
 * AC-DLA-56 - every product table is a DataGrid. Zero files under `app/**`
 * or `components/platform/**` import `@/components/ui/table` or render a
 * raw `<table` outside the two content allowlist entries (a form's table
 * FIELD and a rendered email block are content, not lists - `D8`/AC-DLA-56's
 * own wording). `components/ui/**` is excluded from the scan on purpose:
 * `table.tsx` and `data-grid-table.tsx` are the PRIMITIVES themselves, not
 * product consumers.
 *
 * The scan strips `/* ... *\/` block comments and `// ...` line comments
 * before matching `<table` - several of the migrated files' own commit-
 * message-style doc comments say "off the raw <table> onto DataGrid",
 * which would otherwise false-positive as a live JSX tag.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');

const CONTENT_ALLOWLIST = new Set([
  'components/platform/form-renderer/table-field.tsx',
  'components/platform/email-editor/block-view.tsx',
]);

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}

function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app', 'components/platform'];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) {
        out.push(full);
      }
    }
  };
  for (const root of roots) walk(path.join(repoRoot, root));
  return out;
}

describe('AC-DLA-56 every product table is a DataGrid', () => {
  it('zero files import @/components/ui/table outside the two content entries', () => {
    const offenders = sourceFiles()
      .filter((f) => {
        const rel = f.replace(repoRoot + path.sep, '').split(path.sep).join('/');
        if (CONTENT_ALLOWLIST.has(rel)) return false;
        const src = fs.readFileSync(f, 'utf8');
        return /from ['"]@\/components\/ui\/table['"]/.test(src);
      })
      .map((f) => f.replace(repoRoot + path.sep, ''));
    expect(offenders).toEqual([]);
  });

  it('zero files render a raw <table outside the two content entries', () => {
    const offenders = sourceFiles()
      .filter((f) => {
        const rel = f.replace(repoRoot + path.sep, '').split(path.sep).join('/');
        if (CONTENT_ALLOWLIST.has(rel)) return false;
        const src = stripComments(fs.readFileSync(f, 'utf8'));
        return /<table(\s|>)/.test(src);
      })
      .map((f) => f.replace(repoRoot + path.sep, ''));
    expect(offenders).toEqual([]);
  });

  it('the content allowlist is exact - both entries exist and DO render a raw <table (content, not a list)', () => {
    for (const rel of CONTENT_ALLOWLIST) {
      const full = path.join(repoRoot, rel);
      expect(fs.existsSync(full), `${rel} should exist`).toBe(true);
      const src = stripComments(fs.readFileSync(full, 'utf8'));
      expect(/<table(\s|>)/.test(src), `${rel} should render a raw <table`).toBe(true);
    }
  });
});
