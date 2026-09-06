import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listConnections = vi.fn();
const listCompanies = vi.fn();
const listSqlConnections = vi.fn();

vi.mock('@/services/integration-service', () => ({
  integrationService: { list: (...args: unknown[]) => listConnections(...args) },
}));
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCompanies: (...args: unknown[]) => listCompanies(...args),
    listSqlConnections: (...args: unknown[]) => listSqlConnections(...args),
  },
}));

const { useAutocountSourceConnections } = await import('./use-autocount-connections');

const API = [
  { id: 'conn-api-1', name: 'AutoCount HQ', provider: 'autocount' },
  { id: 'conn-api-2', name: 'AutoCount Branch', provider: 'autocount' },
];
const SQL = [
  { id: 'conn-sql-1', name: 'SQL HQ', dialect: 'mssql', database: 'AED_HQ' },
  { id: 'conn-sql-2', name: 'SQL Branch', dialect: 'mssql', database: 'AED_BRANCH' },
];

function companies(...connectionIds: string[]) {
  return { data: connectionIds.map((id) => ({ id: `c-${id}`, connectionId: id })), total: 1, page: 0 };
}

beforeEach(() => {
  listConnections.mockReset().mockResolvedValue({ data: API, total: 2, page: 0 });
  listSqlConnections.mockReset().mockResolvedValue(SQL);
  listCompanies.mockReset().mockResolvedValue(companies());
});

async function loaded() {
  const hook = renderHook(() => useAutocountSourceConnections());
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook.result.current;
}

describe('useAutocountSourceConnections (plan sprint-5/01, AC-01-12)', () => {
  it('excludes connections already bound to a company from BOTH pickers', async () => {
    listCompanies.mockResolvedValue(companies('conn-api-1', 'conn-sql-1'));
    const r = await loaded();
    expect(r.api.options.map((o) => o.value)).toEqual(['conn-api-2']);
    expect(r.db.options.map((o) => o.value)).toEqual(['conn-sql-2']);
    // The database IS the DB company's identity, so the label carries it.
    expect(r.db.options[0].label).toBe('SQL Branch · AED_BRANCH');
  });

  it('defaults to API when both sources have an unbound connection', async () => {
    expect((await loaded()).defaultKind).toBe('api');
  });

  it('defaults to DB when only the SQL source has an unbound connection', async () => {
    listConnections.mockResolvedValue({ data: [], total: 0, page: 0 });
    const r = await loaded();
    expect(r.defaultKind).toBe('db');
    expect(r.api.hasAny).toBe(false);
  });

  it('defaults to DB when every API connection is already bound', async () => {
    listCompanies.mockResolvedValue(companies('conn-api-1', 'conn-api-2'));
    const r = await loaded();
    expect(r.defaultKind).toBe('db');
    expect(r.api.allBound).toBe(true);
  });

  it('falls back to API when neither source has anything to pick', async () => {
    listConnections.mockResolvedValue({ data: [], total: 0, page: 0 });
    listSqlConnections.mockResolvedValue([]);
    const r = await loaded();
    expect(r.defaultKind).toBe('api');
    expect(r.db.hasAny).toBe(false);
    expect(r.db.allBound).toBe(false);
  });

  it('reports allBound for the SQL source when every connection is a company', async () => {
    listCompanies.mockResolvedValue(companies('conn-sql-1', 'conn-sql-2'));
    const r = await loaded();
    expect(r.db.hasAny).toBe(true);
    expect(r.db.allBound).toBe(true);
    expect(r.db.options).toEqual([]);
  });

  it('a failing SQL-connections call degrades to "none" rather than breaking the API picker', async () => {
    listSqlConnections.mockRejectedValue(new Error('boom'));
    const r = await loaded();
    expect(r.db.hasAny).toBe(false);
    expect(r.api.options).toHaveLength(2);
  });
});
