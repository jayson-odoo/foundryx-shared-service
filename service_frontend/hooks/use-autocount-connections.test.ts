import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const listApiConnections = vi.fn();
const listCompanies = vi.fn();
const listSqlConnections = vi.fn();

vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listApiConnections: (...args: unknown[]) => listApiConnections(...args),
    listCompanies: (...args: unknown[]) => listCompanies(...args),
    listSqlConnections: (...args: unknown[]) => listSqlConnections(...args),
  },
}));

const { useAutocountSourceConnections } = await import('./use-autocount-connections');

const API = [
  { id: 'conn-api-1', name: 'AutoCount HQ', baseUrl: 'https://hapi.sorento.cc.cd/api/db1', auth: 'none' },
  { id: 'conn-api-2', name: 'AutoCount Branch', baseUrl: 'https://api.autocountcloud.com', auth: 'basic' },
];
const SQL = [
  { id: 'conn-sql-1', name: 'SQL HQ', dialect: 'mssql', database: 'AED_HQ' },
  { id: 'conn-sql-2', name: 'SQL Branch', dialect: 'mssql', database: 'AED_BRANCH' },
];

function companies(...connectionIds: string[]) {
  return { data: connectionIds.map((id) => ({ id: `c-${id}`, connectionId: id })), total: 1, page: 0 };
}

beforeEach(() => {
  listApiConnections.mockReset().mockResolvedValue(API);
  listSqlConnections.mockReset().mockResolvedValue(SQL);
  listCompanies.mockReset().mockResolvedValue(companies());
});

async function loaded() {
  const hook = renderHook(() => useAutocountSourceConnections());
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook.result.current;
}

describe('useAutocountSourceConnections (plan sprint-5/01, AC-01-12; sprint-5/08 AC-08-09/15)', () => {
  it('excludes connections already bound to a company from BOTH pickers', async () => {
    listCompanies.mockResolvedValue(companies('conn-api-1', 'conn-sql-1'));
    const r = await loaded();
    expect(r.api.options.map((o) => o.value)).toEqual(['conn-api-2']);
    expect(r.db.options.map((o) => o.value)).toEqual(['conn-sql-2']);
    // The database IS the DB company's identity, so the label carries it.
    expect(r.db.options[0].label).toBe('SQL Branch · AED_BRANCH');
  });

  it('labels each API option with its auth mode (AC-08-09)', async () => {
    const r = await loaded();
    expect(r.api.options).toEqual([
      { label: 'AutoCount HQ (No auth)', value: 'conn-api-1' },
      { label: 'AutoCount Branch (Basic auth)', value: 'conn-api-2' },
    ]);
    expect(r.apiConnectionsById['conn-api-1'].auth).toBe('none');
    expect(r.apiConnectionsById['conn-api-2'].auth).toBe('basic');
  });

  it('drops a bound connection from apiConnectionsById too', async () => {
    listCompanies.mockResolvedValue(companies('conn-api-1'));
    const r = await loaded();
    expect(Object.keys(r.apiConnectionsById)).toEqual(['conn-api-2']);
  });

  it('defaults to API when both sources have an unbound connection', async () => {
    expect((await loaded()).defaultKind).toBe('api');
  });

  it('defaults to DB when only the SQL source has an unbound connection', async () => {
    listApiConnections.mockResolvedValue([]);
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
    listApiConnections.mockResolvedValue([]);
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

  it('a failing API-connections call degrades to "none" rather than breaking the SQL picker', async () => {
    listApiConnections.mockRejectedValue(new Error('boom'));
    const r = await loaded();
    expect(r.api.hasAny).toBe(false);
    expect(r.apiConnectionsById).toEqual({});
    expect(r.db.options).toHaveLength(2);
  });
});
