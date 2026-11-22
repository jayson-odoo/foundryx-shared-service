import { describe, expect, it } from 'vitest';
import { leadListParams, sourceListParams } from './lead-capture-sources-service';
import type { ListQuery } from '@/types/resource';

const base: ListQuery = { page: 1, pageSize: 25 };

describe('lead capture list params', () => {
  it('sends server sort only for known columns', () => {
    expect(leadListParams({ ...base, sort: { id: 'email', desc: false } }).toString()).toContain('sort=email&order=asc');
    expect(leadListParams({ ...base, sort: { id: 'name', desc: true } }).has('sort')).toBe(false);
    expect(sourceListParams({ ...base, sort: { id: 'leads7d', desc: true } }).get('order')).toBe('desc');
  });

  it('flattens multi-select and date filters', () => {
    const p = leadListParams(
      {
        ...base,
        search: 'ann',
        filter: {
          kind: 'group',
          combinator: 'and',
          rules: [
            { kind: 'condition', field: 'source', operator: 'in', value: ['s1', 's2'] },
            { kind: 'condition', field: 'isTest', operator: 'is_false', value: null },
            { kind: 'condition', field: 'receivedAt', operator: 'between', value: ['2026-11-01', '2026-11-15'] },
            { kind: 'condition', field: 'unknown', operator: 'eq', value: 'x' },
          ],
        },
      },
      's0',
    );
    expect(p.getAll('source')).toEqual(['s0', 's1', 's2']);
    expect(p.get('isTest')).toBe('false');
    expect(p.get('receivedFrom')).toBe('2026-11-01');
    expect(p.get('receivedTo')).toBe('2026-11-15');
    expect(p.has('unknown')).toBe(false);
    expect(p.get('search')).toBe('ann');
    expect(p.get('page')).toBe('1');
  });

  it('ignores OR groups rather than narrowing wrongly', () => {
    const p = sourceListParams({
      ...base,
      filter: { kind: 'group', combinator: 'or', rules: [{ kind: 'condition', field: 'status', operator: 'in', value: ['LIVE'] }] },
    });
    expect(p.has('status')).toBe(false);
  });
});
