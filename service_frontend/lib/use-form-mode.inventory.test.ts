/**
 * AC-DLA-61 - every VALIDATING `useForm(` call (one that passes a `resolver`,
 * a zod schema wired through `zodResolver`) sets `mode: 'onTouched'` - errors
 * surface the moment a field is left, not only after a failed submit. A
 * `useForm()`/`useForm({ defaultValues })` call with no `resolver` is not
 * "validating" and is out of this AC's scope (the plan's own wording: "every
 * VALIDATING useForm( call").
 *
 * Also guards the AC's second half: zero `setTimeout(...)` whose body calls
 * `form.reset` (a hand-rolled delayed reset is the anti-pattern this AC
 * bans outright - baseline 0, kept there).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app', 'components', 'hooks'];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (
        (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts')) &&
        !entry.name.includes('.test.')
      ) {
        out.push(full);
      }
    }
  };
  for (const root of roots) walk(path.join(repoRoot, root));
  return out;
}

/** The `useForm(...)`/`useForm<T>(...)` call's argument object, brace-depth
 *  tracked (the options object itself may contain nested braces/generics). */
function findUseFormCalls(src: string): string[] {
  const out: string[] = [];
  const opener = /useForm(?:<[^>(]*>)?\(/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(src))) {
    let i = m.index + m[0].length;
    let depth = 1; // the opening `(` itself
    const start = i;
    while (i < src.length && depth > 0) {
      if (src[i] === '(') depth += 1;
      else if (src[i] === ')') depth -= 1;
      i += 1;
    }
    out.push(src.slice(start, i - 1));
  }
  return out;
}

describe('AC-DLA-61 every validating useForm( sets mode: onTouched', () => {
  it('every useForm( call with a resolver also carries mode: \'onTouched\' (allowlist empty)', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('useForm')) continue;
      const rel = file.replace(repoRoot + path.sep, '');
      for (const call of findUseFormCalls(src)) {
        if (!/resolver\s*:/.test(call)) continue;
        if (!/mode\s*:\s*['"]onTouched['"]/.test(call)) {
          offenders.push(rel);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('AC-DLA-61 no delayed form.reset', () => {
  it('zero setTimeout(...) bodies call form.reset (baseline 0, guarded)', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const src = fs.readFileSync(file, 'utf8');
      if (!src.includes('setTimeout')) continue;
      // A setTimeout callback whose body (within ~200 chars) calls
      // `<something>.reset(` - loose enough to catch `form.reset(` and a
      // renamed form variable's `.reset(`, tight enough not to fire on an
      // unrelated setTimeout elsewhere in the same file.
      if (/setTimeout\([^)]*=>[\s\S]{0,200}?\.reset\(/.test(src)) {
        offenders.push(file.replace(repoRoot + path.sep, ''));
      }
    }
    expect(offenders).toEqual([]);
  });
});
