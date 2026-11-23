/**
 * Foundryx UIUX switch scope guard (playbook-uiux.md): with the switch off (no
 * `data-fx="on"` on <html>) the sanctioned CSS files must behave exactly as
 * before. So, across the four sanctioned CSS files:
 *
 * 1. every `--fx-*` custom property is defined only under `[data-fx="on"]`;
 * 2. every rule that names an fx hook (`data-fx...`, `.fx-...`, `var(--fx-`)
 *    sits under `[data-fx="on"]`, unless it is an `@utility fx-*` block (a
 *    class only fx components use);
 * 3. nothing under `[data-fx="on"]` redefines an existing (non `--fx-`)
 *    custom property;
 * 4. an `@utility fx-*` block defines no custom property of its own.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(__dirname, '..');
const FILES = [
  'css/config.reui.css',
  'css/foundryx-tokens.css',
  'css/styles.css',
  'css/demos/demo1.css',
];

interface Rule {
  file: string;
  chain: string[];
  declarations: string[];
}

/** Brace-balanced walk: every block with declarations, with its preludes. */
function rules(file: string): Rule[] {
  const css = fs
    .readFileSync(path.join(root, file), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '');
  const out: Rule[] = [];
  const walk = (text: string, chain: string[]) => {
    let i = 0;
    let buffer = '';
    const own: string[] = [];
    while (i < text.length) {
      const ch = text[i];
      if (ch === '{') {
        let depth = 1;
        let j = i + 1;
        while (j < text.length && depth > 0) {
          if (text[j] === '{') depth += 1;
          else if (text[j] === '}') depth -= 1;
          j += 1;
        }
        walk(text.slice(i + 1, j - 1), [...chain, buffer.trim()]);
        buffer = '';
        i = j;
        continue;
      }
      if (ch === ';') {
        const decl = buffer.trim();
        if (decl && !decl.startsWith('@')) own.push(decl);
        buffer = '';
      } else {
        buffer += ch;
      }
      i += 1;
    }
    const tail = buffer.trim();
    if (tail && !tail.startsWith('@')) own.push(tail);
    if (own.length) out.push({ file, chain, declarations: own });
  };
  walk(css, []);
  return out;
}

const ALL = FILES.flatMap(rules);
const ON = /\[data-fx=(['"])on\1\]/;
const underSwitch = (rule: Rule) =>
  rule.chain.some((prelude) => ON.test(prelude));
const fxUtility = (rule: Rule) =>
  rule.chain.some((prelude) => /^@utility\s+fx-/.test(prelude));
const propName = (decl: string) => decl.slice(0, decl.indexOf(':')).trim();
const where = (rule: Rule) => `${rule.file}: ${rule.chain.join(' > ')}`;

describe('Foundryx UIUX switch scope (four sanctioned CSS files)', () => {
  it('defines --fx-* custom properties only under [data-fx="on"]', () => {
    const offenders = ALL.filter(
      (rule) =>
        !underSwitch(rule) &&
        rule.declarations.some((decl) => propName(decl).startsWith('--fx-')),
    ).map(where);
    expect(offenders).toEqual([]);
  });

  it('keeps every rule that names an fx hook under [data-fx="on"] (fx utilities aside)', () => {
    const namesFx = (rule: Rule) =>
      rule.chain.some((prelude) => /data-fx|\.fx-/.test(prelude)) ||
      rule.declarations.some((decl) => decl.includes('var(--fx-'));
    const offenders = ALL.filter(
      (rule) => namesFx(rule) && !underSwitch(rule) && !fxUtility(rule),
    ).map(where);
    expect(offenders).toEqual([]);
  });

  it('redefines no existing custom property under [data-fx="on"]', () => {
    const offenders = ALL.filter(underSwitch).flatMap((rule) =>
      rule.declarations
        .map(propName)
        .filter((name) => name.startsWith('--') && !name.startsWith('--fx-'))
        .map((name) => `${where(rule)}: ${name}`),
    );
    expect(offenders).toEqual([]);
  });

  it('gives fx utilities no custom properties of their own', () => {
    const offenders = ALL.filter(fxUtility).flatMap((rule) =>
      rule.declarations.map(propName).filter((name) => name.startsWith('--')),
    );
    expect(offenders).toEqual([]);
  });

  it('actually carries the switch tokens (the guard is not vacuous)', () => {
    const fxProps = new Set(
      ALL.filter(underSwitch).flatMap((rule) =>
        rule.declarations.map(propName),
      ),
    );
    for (const token of [
      '--fx-act',
      '--fx-ink-3',
      '--fx-ease-out',
      '--fx-t-hover',
      '--fx-r-m',
      '--fx-z-tip',
      '--fx-font',
    ]) {
      expect(fxProps.has(token), token).toBe(true);
    }
  });
});
