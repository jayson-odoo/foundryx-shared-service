/**
 * Owner's local check (FX-26): Cancel and Back on new and record pages left
 * without asking about typed values. Every form hook built its
 * `ResourceFormConfig` in a `useMemo` and read `form.formState.isDirty`
 * inside it, without it in the deps, so `config.isDirty` kept its first
 * value (false) and the shell's discard guard never asked. The hooks now read
 * it outside the memo and list it; this guard keeps the pattern out.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(__dirname, '../../..');

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : walk(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

describe('form configs read isDirty where React sees it change', () => {
  it('no config sets `isDirty:` straight from `formState.isDirty` unless its deps list it', () => {
    const offenders = [...walk(path.join(root, 'app')), ...walk(path.join(root, 'components'))]
      .filter((file) => {
        const src = fs.readFileSync(file, 'utf8');
        const inConfig = /\bisDirty:[^,\n]*\.formState\.isDirty\b/.test(src);
        const inDeps = /\[[^\]\n]*\.formState\.isDirty[^\]\n]*\]\s*,?\s*\)/.test(src);
        return inConfig && !inDeps;
      })
      .map((file) => path.relative(root, file));
    expect(offenders).toEqual([]);
  });
});
