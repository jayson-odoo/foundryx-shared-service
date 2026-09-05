/**
 * AC-DLA-63 - proves the `local/no-px-text-class` rule (declared in
 * `eslint.config.mjs`) actually fires, rather than trusting the config
 * wiring by inspection alone. Ported from `sorento_crm`
 * `eslint.config.text-px-rule.test.ts` (S9-01) verbatim in shape.
 *
 * Drives the rule through ESLint's own `Linter` class instead of mounting a
 * component: this is a lint rule, not a component, and the config array's
 * `files`/`ignores` scoping (the demo1 layout exempt, AC-DLA-63) is covered
 * separately below by asserting on the resolved config object itself.
 */
import { Linter } from 'eslint';
import { describe, it, expect } from 'vitest';
import eslintConfig, { noPxTextClassRule } from './eslint.config.mjs';

const JSX_LANGUAGE_OPTIONS = {
  ecmaVersion: 2022 as const,
  sourceType: 'module' as const,
  parserOptions: { ecmaFeatures: { jsx: true } },
};

function lint(code: string) {
  const linter = new Linter();
  // `noPxTextClassRule` is a plain object exported from the untyped .mjs
  // config file, so it does not structurally match ESLint's strict
  // `RuleDefinition` TS type - this is an interop cast, not a hidden
  // application bug.
  const config = {
    languageOptions: JSX_LANGUAGE_OPTIONS,
    plugins: { local: { rules: { 'no-px-text-class': noPxTextClassRule } } },
    rules: { 'local/no-px-text-class': 'error' },
  } as Linter.Config;
  return linter.verify(code, config);
}

describe('AC-DLA-63 - text-[Npx] guardrail fires', () => {
  it('flags an arbitrary px text size in a plain className string', () => {
    const messages = lint(`const x = <div className="foo text-[13px] bar" />;`);
    expect(messages).toHaveLength(1);
    expect(messages[0].ruleId).toBe('local/no-px-text-class');
    expect(messages[0].message).toContain('text-[13px]');
  });

  it('flags an arbitrary px text size inside a template literal (cn(...) usage)', () => {
    const messages = lint(
      'const x = <div className={`foo ${active ? "text-[11px]" : "text-sm"}`} />;',
    );
    expect(messages.some((m) => m.ruleId === 'local/no-px-text-class')).toBe(true);
  });

  it('does not flag a type-scale step', () => {
    const messages = lint(`const x = <div className="foo text-sm bar" />;`);
    expect(messages).toHaveLength(0);
  });

  it('does not flag an unrelated bracket class', () => {
    // A plausible false-positive shape: an arbitrary value that is not a
    // font-size utility at all.
    const messages = lint(`const x = <div className="w-[13px] top-[2px]" />;`);
    expect(messages).toHaveLength(0);
  });

  it('reports every occurrence when more than one is present', () => {
    const messages = lint(`const x = <div className="text-[10px] text-[12px]" />;`);
    expect(messages).toHaveLength(2);
  });
});

describe('AC-DLA-63 - text-[Npx] guardrail is scoped correctly in eslint.config.mjs', () => {
  const enabling = eslintConfig.find(
    (c) =>
      Array.isArray((c as { files?: string[] }).files) &&
      (c as { rules?: Record<string, unknown> }).rules?.['local/no-px-text-class'] === 'error',
  ) as { ignores?: string[] } | undefined;

  it('the error-level config object exists and exempts the demo1 layout', () => {
    expect(enabling).toBeTruthy();
    expect(enabling?.ignores).toContain('app/components/layouts/demo1/**');
  });
});
