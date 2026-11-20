import { describe, expect, it } from 'vitest';
import { emptyCombine, simulateCombine } from './autocount-combine';
import type { AutocountCombineConfig } from '@/types/autocount';

describe('emptyCombine', () => {
  it('every list starts empty, measure blank', () => {
    const c = emptyCombine();
    expect(c.computed).toEqual([]);
    expect(c.groupBy).toEqual([]);
    expect(c.measure).toBe('');
  });
});

// A compact mirror of the stock preset's shape (AC-10-41) - real column
// names, small enough to hand-verify the funnel by eye.
function stockLikeConfig(): AutocountCombineConfig {
  return {
    computed: [
      {
        alias: 'base_qty',
        formula: 'if(lower(trim(UOM)) == lower(trim(BaseUOM)), number(BalQty), number(BalQty) * number(Rate))',
      },
    ],
    require: [{ name: 'uom_rate', formula: 'number(default(Rate, 1)) > 0', reason: 'uom_rate_unresolved' }],
    measure: 'base_qty',
    groupBy: ['ItemCode', 'Location'],
    measures: [{ source: 'base_qty', op: 'sum', alias: 'qty' }],
    carry: ['ItemDescription'],
    round: [{ measure: 'qty', mode: 'half_up', dp: 0 }],
    drop: [
      { name: 'zero', formula: 'qty == 0' },
      { name: 'negative', formula: 'qty < 0', listRows: true },
    ],
  };
}

describe('simulateCombine (PHASE 1 MOCK client-side funnel)', () => {
  it('groups, sums, rounds and drops zero/negative groups', () => {
    const rows = [
      { ItemCode: 'A', Location: 'WH1', UOM: 'UNIT', BaseUOM: 'UNIT', Rate: 1, BalQty: 5, ItemDescription: 'Widget' },
      { ItemCode: 'A', Location: 'WH1', UOM: 'UNIT', BaseUOM: 'UNIT', Rate: 1, BalQty: 3, ItemDescription: 'Widget' },
      { ItemCode: 'B', Location: 'WH1', UOM: 'UNIT', BaseUOM: 'UNIT', Rate: 1, BalQty: 0, ItemDescription: 'Gadget' },
      { ItemCode: 'C', Location: 'WH1', UOM: 'UNIT', BaseUOM: 'UNIT', Rate: 1, BalQty: -2, ItemDescription: 'Gizmo' },
    ];
    const result = simulateCombine(rows, stockLikeConfig());
    expect(result.rowsIn).toBe(4);
    expect(result.excludedCount).toBe(0);
    expect(result.groups).toBe(3);
    expect(result.dropped.zero.count).toBe(1);
    expect(result.dropped.negative.count).toBe(1);
    expect(result.dropped.negative.rows).toHaveLength(1);
    expect(result.rowsOut).toBe(1);
    expect(result.rows[0]).toMatchObject({ ItemCode: 'A', Location: 'WH1', qty: 8 });
  });

  it('a require rule excludes a row, carrying its groupBy + measure raw value', () => {
    const rows = [
      { ItemCode: 'A', Location: 'WH1', UOM: 'ctn', BaseUOM: 'UNIT', Rate: 0, BalQty: 4, ItemDescription: 'X' },
    ];
    const result = simulateCombine(rows, stockLikeConfig());
    expect(result.excludedCount).toBe(1);
    expect(result.excludedRows[0].reason).toBe('uom_rate_unresolved');
    expect(result.excludedRows[0].ItemCode).toBe('A');
    expect(result.rowsOut).toBe(0);
  });

  it('a formula fault in require is a named exclusion, never a throw', () => {
    const config: AutocountCombineConfig = {
      ...emptyCombine(),
      require: [{ name: 'r', formula: 'number(Missing)', reason: 'bad' }],
      groupBy: ['ItemCode'],
      measure: 'BalQty',
    };
    expect(() => simulateCombine([{ ItemCode: 'A' }], config)).not.toThrow();
    const result = simulateCombine([{ ItemCode: 'A' }], config);
    expect(result.excludedRows[0].reason).toBe('require_error');
  });

  it('rounding counts a group whose value actually changed', () => {
    const config: AutocountCombineConfig = {
      ...emptyCombine(),
      groupBy: ['ItemCode'],
      measure: 'qty',
      measures: [{ source: 'qty', op: 'sum', alias: 'qty' }],
      round: [{ measure: 'qty', mode: 'half_up', dp: 0 }],
    };
    const result = simulateCombine([{ ItemCode: 'A', qty: 1.6 }, { ItemCode: 'B', qty: 2 }], config);
    expect(result.roundedCount).toBe(1);
  });
});
