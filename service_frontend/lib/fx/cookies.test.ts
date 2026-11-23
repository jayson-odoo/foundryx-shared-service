import { describe, expect, it } from 'vitest';
import {
  cookieAssignment,
  FX_DEFAULT_THEME,
  fxHtmlAttributes,
  isFxOnValue,
  parseFxTheme,
  readCookie,
  serializeFxTheme,
} from './cookies';

describe('fx_uiux cookie', () => {
  it('is on only for the exact value "on"', () => {
    expect(isFxOnValue('on')).toBe(true);
    for (const junk of [undefined, null, '', 'off', 'ON', 'true', '1', 'on ']) {
      expect(isFxOnValue(junk as string | undefined)).toBe(false);
    }
  });

  it('writes on for a year and deletes rather than writing off', () => {
    expect(cookieAssignment('fx_uiux', 'on', false)).toBe(
      'fx_uiux=on; Path=/; Max-Age=31536000; SameSite=Lax',
    );
    expect(cookieAssignment('fx_uiux', null, false)).toBe(
      'fx_uiux=; Path=/; Max-Age=0; SameSite=Lax',
    );
    expect(cookieAssignment('fx_uiux', 'on', true)).toMatch(/; Secure$/);
  });

  it('reads one cookie out of a cookie string', () => {
    expect(
      readCookie('a=1; fx_uiux=on; fx_theme=sand.forest.inter.110', 'fx_uiux'),
    ).toBe('on');
    expect(readCookie('a=1; fx_theme=sand.forest.inter.110', 'fx_theme')).toBe(
      'sand.forest.inter.110',
    );
    expect(readCookie('a=1', 'fx_uiux')).toBeUndefined();
    expect(readCookie('', 'fx_uiux')).toBeUndefined();
  });
});

describe('fx_theme cookie', () => {
  it('defaults to Slate, Midnight, Geist, 90% with no cookie', () => {
    expect(parseFxTheme(undefined)).toEqual({
      pal: 'slate',
      dpal: 'midnight',
      font: 'geist',
      scale: 90,
    });
    expect(parseFxTheme('')).toEqual(FX_DEFAULT_THEME);
  });

  it('round-trips a valid theme', () => {
    const theme = {
      pal: 'mint',
      dpal: 'graphite',
      font: 'dmsans',
      scale: 120,
    } as const;
    expect(parseFxTheme(serializeFxTheme(theme))).toEqual(theme);
    expect(serializeFxTheme(FX_DEFAULT_THEME)).toBe('slate.midnight.geist.90');
  });

  it('ignores junk part by part, keeping the valid parts', () => {
    expect(parseFxTheme('sand.neon.comic.95')).toEqual({
      pal: 'sand',
      dpal: 'midnight',
      font: 'geist',
      scale: 90,
    });
    expect(parseFxTheme('midnight.slate.inter.110')).toEqual({
      pal: 'slate',
      dpal: 'midnight',
      font: 'inter',
      scale: 110,
    });
    expect(parseFxTheme('<script>.x')).toEqual(FX_DEFAULT_THEME);
    expect(parseFxTheme('a'.repeat(500))).toEqual(FX_DEFAULT_THEME);
  });
});

describe('fxHtmlAttributes', () => {
  it('adds nothing at all while off', () => {
    expect(
      fxHtmlAttributes(false, {
        pal: 'mint',
        dpal: 'forest',
        font: 'inter',
        scale: 120,
      }),
    ).toEqual({});
  });

  it('sets the switch, palette, font and size while on', () => {
    expect(fxHtmlAttributes(true, FX_DEFAULT_THEME)).toEqual({
      'data-fx': 'on',
      'data-fx-pal': 'slate',
      'data-fx-dpal': 'midnight',
      'data-fx-font': 'geist',
      style: { '--fx-scale': '0.9' },
    });
  });
});
