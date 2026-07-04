/**
 * Branding token helpers (sprint-2/03 §TDD — frontend):
 * whitelist validation · default-equal values normalize away · transparent
 * derivation · CSS/var emission · template roundtrip.
 */
import { describe, expect, it } from 'vitest';
import {
  buildTemplate,
  deriveTransparent,
  FOUNDRYX_DEFAULTS,
  effectiveTokens,
  isValidColor,
  normalizeHex,
  overrideVars,
  parseTemplateFile,
  TOKEN_DEFS,
  tokensToCss,
  validateTokens,
} from './branding-tokens';

describe('whitelist + defaults', () => {
  it('defaults cover every whitelisted key in both themes', () => {
    for (const d of TOKEN_DEFS) {
      expect(FOUNDRYX_DEFAULTS.light[d.key], `light.${d.key}`).toBeDefined();
      expect(FOUNDRYX_DEFAULTS.dark[d.key], `dark.${d.key}`).toBeDefined();
    }
  });

  it('every default is a valid color', () => {
    for (const theme of ['light', 'dark'] as const) {
      for (const v of Object.values(FOUNDRYX_DEFAULTS[theme])) {
        expect(isValidColor(v), v).toBe(true);
      }
    }
  });
});

describe('isValidColor / normalizeHex', () => {
  it('accepts #RGB, #RRGGBB, #RRGGBBAA', () => {
    expect(isValidColor('#abc')).toBe(true);
    expect(isValidColor('#A1B2C3')).toBe(true);
    expect(isValidColor('#a1b2c3ff')).toBe(true);
  });

  it('rejects names, rgb() and junk', () => {
    expect(isValidColor('red')).toBe(false);
    expect(isValidColor('rgb(1,2,3)')).toBe(false);
    expect(isValidColor('#ab')).toBe(false);
    expect(isValidColor('')).toBe(false);
  });

  it('expands shorthand', () => {
    expect(normalizeHex('#F0A')).toBe('#ff00aa');
  });
});

describe('validateTokens', () => {
  it('rejects unknown keys with a named error', () => {
    const { tokens, errors } = validateTokens({
      light: { 'not-a-token': '#fff' },
    });
    expect(tokens).toBeNull();
    expect(errors[0]).toContain('not-a-token');
  });

  it('rejects non-color values with a named error', () => {
    const { tokens, errors } = validateTokens({ dark: { primary: 'blue' } });
    expect(tokens).toBeNull();
    expect(errors[0]).toContain('dark.primary');
  });

  it('rejects unknown top-level sections', () => {
    const { errors } = validateTokens({ light: {}, midnight: {} });
    expect(errors[0]).toContain('midnight');
  });

  it('normalizes default-equal values away (unchanged template = no overrides)', () => {
    const { tokens, errors } = validateTokens(buildTemplate(null));
    expect(errors).toEqual([]);
    expect(tokens).toBeNull();
  });

  it('keeps true diffs only', () => {
    const { tokens } = validateTokens({
      light: { primary: '#0050ff', success: FOUNDRYX_DEFAULTS.light['success'] },
      dark: {},
    });
    expect(tokens).toEqual({ light: { primary: '#0050ff' }, dark: {} });
  });
});

describe('derivation + emission', () => {
  it('derives the transparent companion at 0.2 alpha', () => {
    expect(deriveTransparent('#ff5a00')).toBe('rgba(255, 90, 0, 0.2)');
  });

  it('overrideVars emits only overridden vars + derived transparents', () => {
    const vars = overrideVars(
      { light: { primary: '#0050ff' }, dark: {} },
      'light',
    );
    expect(vars).toEqual({
      '--foundryx-primary': '#0050ff',
      '--foundryx-primary-transparent': 'rgba(0, 80, 255, 0.2)',
    });
    expect(
      overrideVars({ light: { primary: '#0050ff' }, dark: {} }, 'dark'),
    ).toEqual({});
  });

  it('tokensToCss renders :root and .dark blocks for the overridden side only', () => {
    const css = tokensToCss({ light: {}, dark: { primary: '#4d82ff' } });
    expect(css).not.toContain(':root');
    expect(css).toContain('.dark {');
    expect(css).toContain('--foundryx-primary: #4d82ff;');
  });

  it('effectiveTokens merges overrides over defaults', () => {
    const t = effectiveTokens(
      { light: { primary: '#0050ff' }, dark: {} },
      'light',
    );
    expect(t['primary']).toBe('#0050ff');
    expect(t['success']).toBe(FOUNDRYX_DEFAULTS.light['success']);
  });
});

describe('template roundtrip', () => {
  it('buildTemplate prefills every key with the effective value', () => {
    const template = buildTemplate({ light: { primary: '#0050ff' }, dark: {} });
    expect(template.light['primary']).toBe('#0050ff');
    expect(Object.keys(template.light)).toHaveLength(TOKEN_DEFS.length);
    expect(Object.keys(template.dark)).toHaveLength(TOKEN_DEFS.length);
  });

  it('parseTemplateFile surfaces JSON syntax errors', () => {
    const { tokens, errors } = parseTemplateFile('{not json');
    expect(tokens).toBeNull();
    expect(errors[0]).toContain('valid JSON');
  });

  it('download → edit one value → upload yields exactly that diff', () => {
    const template = buildTemplate(null);
    template.light['primary'] = '#0050FF';
    const { tokens, errors } = parseTemplateFile(JSON.stringify(template));
    expect(errors).toEqual([]);
    expect(tokens).toEqual({ light: { primary: '#0050ff' }, dark: {} });
  });
});
