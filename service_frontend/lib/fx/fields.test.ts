/**
 * Foundryx UIUX field rules (slice F4): typed dates, the 12-hour moments and
 * relative times against a fixed clock, money (RM for the home currency, the
 * ISO code for the rest), steps and snapping, password strength, secrets.
 */
import { describe, expect, it } from 'vitest';
import {
  formatDate,
  formatDateTime,
  formatFxDate,
  formatFxDateTime,
  formatFxDayKey,
  formatFxDayLine,
  formatFxRelative,
  formatFxTime,
  formatFxZoneLine,
} from '@/lib/datetime';
import {
  formatFxAmount,
  formatMoney,
  formatMoneyFx,
  fxCurrencyDecimals,
  fxCurrencyLabel,
  parseMoneyInput,
} from '@/lib/money';
import { parseTypedDate, passwordStrength, secretEnding, snapToStep, stepValue } from './fields';

const KL = { timeZone: 'Asia/Kuala_Lumpur' };

describe('moments (12-hour clock, viewer zone)', () => {
  it('formats date, time and moment the playbook way', () => {
    expect(formatFxDate('2026-11-14T06:14:00Z', KL)).toBe('14 Nov 2026');
    expect(formatFxDate('2026-11-02T06:14:00Z', KL)).toBe('2 Nov 2026');
    expect(formatFxTime('2026-11-14T06:14:00Z', KL)).toBe('2:14 pm');
    expect(formatFxDateTime('2026-11-14T06:14:00Z', KL)).toBe('14 Nov 2026, 2:14 pm');
  });

  it('reads midnight and noon on the 12-hour clock', () => {
    expect(formatFxTime('2026-11-13T16:05:00Z', KL)).toBe('12:05 am');
    expect(formatFxTime('2026-11-14T04:00:00Z', KL)).toBe('12:00 pm');
    expect(formatFxTime('2026-11-14T03:59:00Z', KL)).toBe('11:59 am');
  });

  it('treats a zone-less timestamp as UTC and renders "-" for nothing', () => {
    expect(formatFxDateTime('2026-11-14T06:14:00', KL)).toBe('14 Nov 2026, 2:14 pm');
    expect(formatFxDateTime(null, KL)).toBe('-');
    expect(formatFxRelative('nonsense', KL)).toBe('-');
  });

  it('leaves the existing formatters exactly as they were', () => {
    expect(formatDateTime('2026-11-14T06:14:00Z', KL)).toBe('14 Nov 2026, 14:14');
    expect(formatDate('2026-11-02T06:14:00Z', KL)).toBe('02 Nov 2026');
  });
});

describe('relative moments against a fixed clock', () => {
  // 14 Nov 2026, 2:14 pm in Kuala Lumpur.
  const now = new Date('2026-11-14T06:14:00Z');
  const rel = (iso: string) => formatFxRelative(iso, { ...KL, now });

  it('reads "now" under a minute', () => {
    expect(rel('2026-11-14T06:14:00Z')).toBe('now');
    expect(rel('2026-11-14T06:13:01Z')).toBe('now');
  });

  it('reads minutes under an hour', () => {
    expect(rel('2026-11-14T06:13:00Z')).toBe('1 min');
    expect(rel('2026-11-14T06:09:00Z')).toBe('5 min');
    expect(rel('2026-11-14T05:14:01Z')).toBe('59 min');
  });

  it('reads hours under a day', () => {
    expect(rel('2026-11-14T05:14:00Z')).toBe('1 h');
    expect(rel('2026-11-14T03:14:00Z')).toBe('3 h');
    expect(rel('2026-11-13T06:14:01Z')).toBe('23 h');
  });

  it('reads "Yesterday" for an older moment on the day before', () => {
    expect(rel('2026-11-13T02:00:00Z')).toBe('Yesterday');
  });

  it('reads the day after that, with the year only for another year', () => {
    expect(rel('2026-11-12T06:14:00Z')).toBe('12 Nov');
    expect(rel('2026-11-01T06:14:00Z')).toBe('1 Nov');
    expect(rel('2025-11-14T06:14:00Z')).toBe('14 Nov 2025');
  });

  it('reads a future moment in full', () => {
    expect(rel('2026-11-15T06:14:00Z')).toBe('15 Nov 2026, 2:14 pm');
  });

  it('counts days in the viewer zone, not UTC', () => {
    // 13 Nov 11:30 pm UTC is already 14 Nov 7:30 am in Kuala Lumpur.
    expect(formatFxDayLine('2026-11-13T23:30:00Z', { ...KL, now })).toBe('Today');
    expect(formatFxDayLine('2026-11-13T23:30:00Z', { timeZone: 'UTC', now })).toBe('Yesterday');
    expect(formatFxDayLine('2026-11-10T06:00:00Z', { ...KL, now })).toBe('10 Nov 2026');
  });
});

describe('zone line', () => {
  it('names the city and the offset in force', () => {
    expect(formatFxZoneLine('Asia/Kuala_Lumpur', new Date('2026-11-14T06:14:00Z'))).toBe('Kuala Lumpur time (GMT+8)');
    expect(formatFxZoneLine('America/New_York', new Date('2026-07-01T00:00:00Z'))).toBe('New York time (GMT-4)');
    expect(formatFxZoneLine('UTC', new Date('2026-07-01T00:00:00Z'))).toBe('UTC time (GMT)');
  });
});

describe('typed dates', () => {
  const today = '2026-11-14';
  it.each([
    ['today', '2026-11-14'],
    ['Tomorrow', '2026-11-15'],
    ['yesterday', '2026-11-13'],
    ['14/11/2026', '2026-11-14'],
    ['1-2-26', '2026-02-01'],
    ['14.11.2026', '2026-11-14'],
    ['14 Nov', '2026-11-14'],
    ['3 december 2027', '2027-12-03'],
    ['Nov 14, 2026', '2026-11-14'],
    ['2026-11-14', '2026-11-14'],
    ['29 Feb 2028', '2028-02-29'],
  ])('reads %s', (text, key) => {
    expect(parseTypedDate(text, today)).toBe(key);
  });

  it.each(['', 'soon', '31/11/2026', '29 Feb 2026', '14 Foo 2026', '2026-13-01'])('cannot read %j', (text) => {
    expect(parseTypedDate(text, today)).toBeNull();
  });

  it('tidies a day key to "14 Nov 2026"', () => {
    expect(formatFxDayKey('2026-11-14')).toBe('14 Nov 2026');
    expect(formatFxDayKey('2026-01-05')).toBe('5 Jan 2026');
    expect(formatFxDayKey('')).toBe('-');
  });
});

describe('money: RM for the home currency, ISO codes for the rest', () => {
  it('writes RM only for MYR', () => {
    expect(fxCurrencyLabel('MYR')).toBe('RM');
    expect(fxCurrencyLabel('myr')).toBe('RM');
    expect(fxCurrencyLabel(null)).toBe('RM');
    expect(fxCurrencyLabel('SGD')).toBe('SGD');
    expect(fxCurrencyLabel('USD')).toBe('USD');
  });

  it('formats amounts with the currency first and its own decimals', () => {
    expect(formatMoneyFx(14000, 'MYR')).toBe('RM 14,000.00');
    expect(formatMoneyFx(14000, 'SGD')).toBe('SGD 14,000.00');
    expect(formatMoneyFx(14000, 'JPY')).toBe('JPY 14,000');
    expect(formatMoneyFx(1234.5, 'USD', 0)).toBe('USD 1,235');
    expect(formatMoneyFx(-12, 'MYR')).toBe('-RM 12.00');
    expect(formatMoneyFx(-0.001, 'MYR')).toBe('RM 0.00');
    expect(formatMoneyFx(null, 'MYR')).toBe('-');
    expect(fxCurrencyDecimals('JPY')).toBe(0);
    expect(fxCurrencyDecimals('XXX-not')).toBe(2);
  });

  it('leaves formatMoney as it was', () => {
    expect(formatMoney(null, 'MYR')).toBe('-');
    expect(formatMoney(5, 'NOPE')).toBe('NOPE 5.00');
  });

  it('reads typed amounts and tidies them', () => {
    expect(parseMoneyInput('14000')).toBe(14000);
    expect(parseMoneyInput('14,000')).toBe(14000);
    expect(parseMoneyInput(' 14,000.5 ')).toBe(14000.5);
    expect(parseMoneyInput('RM 1,234.56')).toBe(1234.56);
    expect(parseMoneyInput('.5')).toBe(0.5);
    expect(parseMoneyInput('-12')).toBe(-12);
    expect(parseMoneyInput('1,23')).toBeNull();
    expect(parseMoneyInput('12abc')).toBeNull();
    expect(parseMoneyInput('')).toBeNull();
    expect(parseMoneyInput('-')).toBeNull();
    expect(formatFxAmount(14000, 2)).toBe('14,000.00');
  });
});

describe('steps', () => {
  it('snaps to the step grid and clamps', () => {
    expect(snapToStep(3.4, 0, 6, 1)).toBe(3);
    expect(snapToStep(3.6, 0, 6, 1)).toBe(4);
    expect(snapToStep(9, 0, 6, 1)).toBe(6);
    expect(snapToStep(-1, 0, 6, 1)).toBe(0);
    expect(snapToStep(0.34, 0, 2, 0.1)).toBe(0.3);
    expect(snapToStep(1.26, 1, 5, 0.5)).toBe(1.5);
  });

  it('greys out at the ends: a step past min or max stays put', () => {
    expect(stepValue(1, -1, 1, 10, 1)).toBe(1);
    expect(stepValue(10, 1, 1, 10, 1)).toBe(10);
    expect(stepValue(5, 1, 1, 10, 1)).toBe(6);
    expect(stepValue(0.3, 1, 0, 2, 0.1)).toBe(0.4);
  });
});

describe('password strength', () => {
  it('stays Weak under 8 characters', () => {
    expect(passwordStrength('Ab1!').label).toBe('Weak');
    expect(passwordStrength('Ab1!').missing).toBe('Use 8 or more characters');
  });

  it('grows with the mix and names the first gap', () => {
    expect(passwordStrength('abcdefgh')).toEqual({ level: 0, label: 'Weak', missing: 'Add a number' });
    expect(passwordStrength('abcdefg1')).toEqual({ level: 1, label: 'Fair', missing: 'Add a capital letter' });
    expect(passwordStrength('Abcdefg1')).toEqual({ level: 2, label: 'Good', missing: 'Add a symbol' });
    expect(passwordStrength('Abcdef1!')).toEqual({ level: 3, label: 'Strong', missing: null });
  });
});

describe('secrets', () => {
  it('names a saved secret by its ending, never its value', () => {
    expect(secretEnding('sk_live_123456a91c')).toBe('ending a91c');
    expect(secretEnding('')).toBe('');
  });
});
