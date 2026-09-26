import { describe, expect, it } from 'vitest';
import { colorToHex, colorToTone } from './color-tone';

/**
 * Review nit (issue #90): `indigo` was mapped to the `info` TONE
 * (`colorToTone`) but missing from `COLOR_NAME_HEX`, so `colorToHex('indigo')`
 * fell through to the gray default - the Triaged status dot (a platform seed
 * status, `ideation/services/statuses.py`) rendered gray instead of indigo.
 */
describe('colorToHex - named colors', () => {
  it('resolves indigo to its own hex, not the gray fallback', () => {
    expect(colorToHex('indigo')).toBe('#6366F1');
    expect(colorToHex('indigo')).not.toBe('#6B7280');
  });

  it('is case-insensitive', () => {
    expect(colorToHex('Indigo')).toBe('#6366F1');
  });

  it('still falls back to gray for a genuinely unknown name', () => {
    expect(colorToHex('mystery-color')).toBe('#6B7280');
  });
});

describe('colorToTone - indigo maps to info (regression)', () => {
  it('keeps indigo on the info tone', () => {
    expect(colorToTone('indigo')).toBe('info');
  });
});
