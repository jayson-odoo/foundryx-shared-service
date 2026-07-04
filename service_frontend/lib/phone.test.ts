import { describe, expect, it } from 'vitest';
import { isValidPhone, normalizePhone } from './phone';

describe('isValidPhone', () => {
  it('accepts E.164 with separators', () => {
    expect(isValidPhone('+65 8900 1234')).toBe(true);
    expect(isValidPhone('+60 12-345 6789')).toBe(true);
    expect(isValidPhone('6589001234')).toBe(true);
  });

  it('rejects junk / too short', () => {
    expect(isValidPhone('asdf')).toBe(false);
    expect(isValidPhone('')).toBe(false);
    expect(isValidPhone('12345')).toBe(false);
    expect(isValidPhone('+0 1234567')).toBe(false); // country code can't start with 0
  });
});

describe('normalizePhone', () => {
  it('keeps a single leading + and strips separators', () => {
    expect(normalizePhone('+65 8900-1234')).toBe('+6589001234');
    expect(normalizePhone('(65) 8900 1234')).toBe('6589001234');
  });
});
