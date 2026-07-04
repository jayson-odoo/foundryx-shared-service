import { describe, expect, it } from 'vitest';
import { aggregateRefs, evaluateExpression, fieldRefs } from './computed-expr';
import { validateFormDoc } from './form-doc';
import type { FormDocument } from '@/types/forms';

const ROWS = [
  { item: 'A', qty: '3' },
  { item: 'B', qty: 5 },
  { item: 'C', qty: null },
];
const vals = { lines: ROWS };

describe('computed aggregate functions (sprint-3/02, FE mirror)', () => {
  it('sum skips non-numeric', () => expect(evaluateExpression('sum(lines.qty)', vals)).toBe(8));
  it('avg over present values', () => expect(evaluateExpression('avg(lines.qty)', vals)).toBe(4));
  it('count is row count', () => expect(evaluateExpression('count(lines)', vals)).toBe(3));
  it('min/max', () => {
    expect(evaluateExpression('min(lines.qty)', vals)).toBe(3);
    expect(evaluateExpression('max(lines.qty)', vals)).toBe(5);
  });
  it('composes with arithmetic', () =>
    expect(evaluateExpression('sum(lines.qty) * 2 + 1', vals)).toBe(17));
  it('empty sum is 0, empty avg is null', () => {
    expect(evaluateExpression('sum(lines.qty)', { lines: [] })).toBe(0);
    expect(evaluateExpression('avg(lines.qty)', { lines: [] })).toBeNull();
  });
  it('splits scalar + aggregate refs', () => {
    expect(Array.from(fieldRefs('sum(lines.qty) + fee') ?? [])).toEqual(['fee']);
    expect(aggregateRefs('sum(lines.qty) + fee')).toEqual([
      { func: 'sum', repeaterKey: 'lines', subKey: 'qty' },
    ]);
  });
});

function doc(...fields: unknown[]): FormDocument {
  return {
    schemaVersion: 1,
    pages: [{ id: 'p1', title: 'P', sections: [{ id: 's1', fields: fields as never }] }],
  } as FormDocument;
}
const repeater = {
  id: 'r1',
  type: 'repeater',
  key: 'lines',
  label: 'Lines',
  repeater: {
    fields: [
      { id: 'rs1', type: 'text', key: 'item', label: 'Item' },
      { id: 'rs2', type: 'number', key: 'qty', label: 'Qty' },
    ],
  },
};
const computed = (expr: string) => ({
  id: 'c1',
  type: 'computed',
  key: 'total',
  label: 'Total',
  computed: { expression: expr },
});

describe('validateFormDoc aggregate gate (FE mirror)', () => {
  it('valid aggregate publishes', () =>
    expect(validateFormDoc(doc(repeater, computed('sum(lines.qty)')))).toEqual([]));
  it('count needs no column', () =>
    expect(validateFormDoc(doc(repeater, computed('count(lines)')))).toEqual([]));
  it('aggregate over non-repeater is blocked', () => {
    const fee = { id: 'n1', type: 'number', key: 'fee', label: 'Fee' };
    expect(validateFormDoc(doc(fee, computed('sum(fee.x)'))).join(' ')).toContain(
      'not an earlier repeater',
    );
  });
  it('aggregate over non-numeric column is blocked', () =>
    expect(validateFormDoc(doc(repeater, computed('sum(lines.item)'))).join(' ')).toContain(
      'not a numeric column',
    ));
  it('forward-ref aggregate is blocked', () =>
    expect(validateFormDoc(doc(computed('sum(lines.qty)'), repeater)).join(' ')).toContain(
      'not an earlier repeater',
    ));
});
