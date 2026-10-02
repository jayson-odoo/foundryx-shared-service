import { describe, expect, it } from 'vitest';
import {
  curatedFields,
  dayInRange,
  formatVendorDateTime,
  formatVendorDay,
  groupSteps,
  lineColumns,
  stepsDone,
  vendorValueText,
} from './autocount-doc-lookup';
import type { DocLookupStep } from '@/types/autocount-doc-lookup';

describe('vendor wall-clock formatting (AC-17-32)', () => {
  it('shows AutoCount dates and times as written, never shifted by a timezone', () => {
    expect(formatVendorDay('2026-10-05')).toBe('05 Oct 2026');
    expect(formatVendorDateTime('2026-10-01T07:39:22.000')).toBe('01 Oct 2026, 07:39');
    expect(formatVendorDay(null)).toBe('-');
  });
});

describe('dayInRange', () => {
  it('is inclusive and false for an unknown range', () => {
    expect(dayInRange('2026-10-01', '2026-10-01', '2026-10-01')).toBe(true);
    expect(dayInRange('2026-10-05', '2026-10-01', '2026-10-01')).toBe(false);
    expect(dayInRange('2026-10-05', null, '2026-10-30')).toBe(false);
  });
});

describe('groupSteps', () => {
  const step = (door: DocLookupStep['door'], day: string, status: DocLookupStep['status'] = 'miss') => ({
    door, day, status, count: 0,
  });

  it('splits known dates, modified-on and DocDate in plan order', () => {
    const groups = groupSteps([
      step('by_doc_date', '2026-10-01'),
      step('by_last_modified', '2026-10-01'),
      step('by_last_modified', '2026-09-30'),
      step('by_doc_date', '2026-10-02'),
    ]);
    expect(groups.map((g) => [g.label, g.steps.length])).toEqual([
      ['Known dates', 1],
      ['Modified on', 2],
      ['DocDate', 1],
    ]);
  });

  it('starts with modified-on when there are no known dates', () => {
    const groups = groupSteps([step('by_last_modified', '2026-10-01'), step('by_doc_date', '2026-10-01')]);
    expect(groups.map((g) => g.label)).toEqual(['Modified on', 'DocDate']);
  });

  it('counts done steps (hit, miss, error)', () => {
    expect(
      stepsDone([
        step('by_doc_date', 'a', 'hit'),
        step('by_doc_date', 'b', 'error'),
        step('by_doc_date', 'c', 'pending'),
        step('by_doc_date', 'd', 'skipped'),
      ]),
    ).toBe(2);
  });
});

describe('record helpers', () => {
  it('curates debtor, ref and net total with currency', () => {
    expect(
      curatedFields({ DebtorCode: '300-R009', DebtorName: 'Anon', Ref: 'X-1', NetTotal: 1250, CurrencyCode: 'MYR' }),
    ).toEqual([
      { label: 'Debtor', value: '300-R009 · Anon' },
      { label: 'Ref', value: 'X-1' },
      { label: 'Net total', value: 'MYR 1,250.00' },
    ]);
  });

  it('keeps only the line columns that exist', () => {
    expect(lineColumns([{ ItemCode: 'A', Qty: 1 }]).map((c) => c.key)).toEqual(['ItemCode', 'Qty']);
  });

  it('renders vendor values as text', () => {
    expect(vendorValueText(null)).toBe('-');
    expect(vendorValueText({ a: 1 })).toBe('{"a":1}');
    expect(vendorValueText(false)).toBe('false');
  });
});
