import { describe, expect, it } from 'vitest';
import { applyClientQuery, type ClientListSpec } from './client-list-query';

interface Row {
  name: string;
  status: string;
  used: string | null;
}

const rows: Row[] = [
  { name: 'Beta', status: 'active', used: '2026-11-02T00:00:00Z' },
  { name: 'alpha', status: 'revoked', used: null },
  { name: 'Gamma', status: 'active', used: '2026-11-01T00:00:00Z' },
];

const spec: ClientListSpec<Row> = {
  searchText: (r) => [r.name],
  value: (r, f) => (f === 'name' ? r.name : f === 'status' ? r.status : f === 'used' ? r.used : null),
};

const base = { page: 0, pageSize: 50 };

describe('applyClientQuery', () => {
  it('searches case-insensitively', () => {
    expect(applyClientQuery(rows, { ...base, search: 'ALP' }, spec).data.map((r) => r.name)).toEqual(['alpha']);
  });

  it('multi-value enum filter matches either value', () => {
    const filter = {
      kind: 'group' as const,
      combinator: 'and' as const,
      rules: [{ kind: 'condition' as const, field: 'status', operator: 'in' as const, value: ['ACTIVE'] }],
    };
    expect(applyClientQuery(rows, { ...base, filter }, spec).total).toBe(2);
  });

  it('sorts both ways and keeps blanks last', () => {
    const asc = applyClientQuery(rows, { ...base, sort: { id: 'used', desc: false } }, spec);
    expect(asc.data.map((r) => r.name)).toEqual(['Gamma', 'Beta', 'alpha']);
    const desc = applyClientQuery(rows, { ...base, sort: { id: 'used', desc: true } }, spec);
    expect(desc.data.map((r) => r.name)).toEqual(['Beta', 'Gamma', 'alpha']);
  });

  it('sort holds across pages', () => {
    const p1 = applyClientQuery(rows, { page: 1, pageSize: 2, sort: { id: 'name', desc: false } }, spec);
    expect(p1.data.map((r) => r.name)).toEqual(['Gamma']);
    expect(p1.total).toBe(3);
  });
});
