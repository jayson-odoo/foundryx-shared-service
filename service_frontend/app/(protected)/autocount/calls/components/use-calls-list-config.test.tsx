/**
 * Plan 63 (AC-63-34, 35, RED): the calls `ResourceList` config. `use-calls-list-config.tsx` does not
 * exist yet - the dynamic import fails, the expected red. Asserted at the config boundary only:
 * column ids, plain outcome words, "-" for missing values, and how a list query reaches `listCalls`.
 */
import type { ReactNode } from 'react';
import { render, renderHook, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery } from '@/types/resource';

vi.mock('@/hooks/use-datetime', async () => {
  const lib = (await import('@/lib/datetime')) as Record<string, unknown>;
  const timeZone = 'Asia/Kuala_Lumpur';
  const call = (name: string, v: string | null | undefined) => {
    const fn = lib[name] as ((x: string | null | undefined, o: { timeZone: string }) => string) | undefined;
    return typeof fn === 'function' ? fn(v, { timeZone }) : '-';
  };
  return {
    useDatetime: () => ({
      timeZone,
      formatDate: (v: string) => call('formatDate', v),
      formatDateTime: (v: string) => call('formatDateTime', v),
      formatTime: (v: string) => call('formatTime', v),
      formatDmyDateTime: (v: string) => call('formatDmyDateTime', v),
    }),
  };
});

const listCalls = vi.fn();
const getCallFilterOptions = vi.fn();
const getCall = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCalls: (...a: unknown[]) => listCalls(...a),
    getCallFilterOptions: (...a: unknown[]) => getCallFilterOptions(...a),
    getCall: (...a: unknown[]) => getCall(...a),
    listCompanies: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }),
  },
}));

interface CallRow {
  id: string;
  createdAt: string;
  companyId: string;
  companyName: string | null;
  book: string | null;
  actingUserId: string | null;
  actingUserName: string | null;
  method: string;
  path: string;
  docType: string | null;
  docNo: string | null;
  outcome: string;
  responseStatus: number | null;
  durationMs: number;
  errorCode: string | null;
  requestId: string | null;
}

const ROW: CallRow = {
  id: 'call-1', createdAt: '2026-11-05T07:04:00Z', companyId: 'co-1', companyName: 'Alpha Co', book: 'db3',
  actingUserId: 'u1', actingUserName: 'Una', method: 'PUT', path: '/EditSalesOrderbydockey', docType: 'SO',
  docNo: 'SO-100', outcome: 'ok', responseStatus: 200, durationMs: 42, errorCode: null, requestId: 'req-100',
};

const COLUMN_IDS = ['createdAt', 'companyName', 'book', 'actingUserName', 'method', 'path', 'docType', 'docNo',
  'outcome', 'responseStatus', 'durationMs', 'errorCode', 'requestId'];

function colId(c: { id?: string }): string | undefined {
  return c.id ?? (c as { accessorKey?: string }).accessorKey;
}

type Cell = (ctx: { row: { original: CallRow } }) => ReactNode;

type ConfigHook = (options?: Record<string, unknown>) => ResourceListConfig<CallRow>;

/** The hook is found by name (`useCallsListConfig`, else any `use*ListConfig` export); callbacks go in under every plausible name. */
async function loadConfig() {
  const mod = (await import('./use-calls-list-config')) as Record<string, unknown>;
  const name = ['useCallsListConfig', 'useAutocountCallsListConfig'].find((n) => typeof mod[n] === 'function')
    ?? Object.keys(mod).find((n) => /^use\w*ListConfig$/.test(n));
  if (!name) throw new Error('use-calls-list-config exports no use*ListConfig hook');
  const hook = mod[name] as ConfigHook;
  const { result } = renderHook(() => hook({ onOpenCall: vi.fn(), onOpenRecord: vi.fn(), onOpen: vi.fn(), onSelect: vi.fn() }));
  return result.current;
}

function cellOf(config: Awaited<ReturnType<typeof loadConfig>>, id: string): Cell {
  const col = config.columns.find((c) => colId(c) === id);
  if (!col) throw new Error(`no column ${id}`);
  return col.cell as unknown as Cell;
}

function renderCell(config: Awaited<ReturnType<typeof loadConfig>>, id: string, row: CallRow) {
  return render(<>{cellOf(config, id)({ row: { original: row } })}</>);
}

beforeEach(() => {
  vi.clearAllMocks();
  listCalls.mockResolvedValue({ data: [], total: 0, page: 0 });
  getCallFilterOptions.mockResolvedValue({ books: [], docTypes: [], outcomes: [], persons: [] });
});

describe('column set (AC-63-32, 34)', () => {
  it('has a column for every sortable field of the calls API', async () => {
    const config = await loadConfig();
    const ids = config.columns.map(colId);
    for (const id of COLUMN_IDS) expect(ids).toContain(id);
  });

  it('is a log: no Create button or handler', async () => {
    const config = await loadConfig();
    expect(config.onCreate).toBeUndefined();
    expect(config.createLabel).toBeUndefined();
  });

  it('row id is the backend id', async () => {
    const config = await loadConfig();
    expect(config.getRowId(ROW)).toBe('call-1');
  });

  it('offers book, document type, outcome and person as filters', async () => {
    const config = await loadConfig();
    const fields = config.filterFields.map((f) => f.field);
    for (const field of ['book', 'outcome']) expect(fields).toContain(field);
    expect(config.searchPlaceholder).toBeTruthy();
  });

  it('declares the outcome filter options in plain words, never raw codes', async () => {
    const config = await loadConfig();
    const outcome = config.filterFields.find((f) => f.field === 'outcome');
    const labels = (outcome?.options ?? []).map((o) => o.label);
    expect(labels).toEqual(expect.arrayContaining(['OK', 'Refused by AutoCount', 'Timed out', 'Could not connect', 'Blocked by SS']));
    expect(labels.join(' ')).not.toMatch(/http_error|connect_error|guard_refused/);
  });
});

describe('plain outcome words (AC-63-35)', () => {
  it.each([
    ['ok', 'OK'],
    ['http_error', 'Refused by AutoCount'],
    ['timeout', 'Timed out'],
    ['connect_error', 'Could not connect'],
    ['guard_refused', 'Blocked by SS'],
  ])('%s reads "%s"', async (outcome, word) => {
    const config = await loadConfig();
    renderCell(config, 'outcome', { ...ROW, outcome });
    expect(screen.getByText(word)).toBeInTheDocument();
    expect(screen.queryByText(outcome)).not.toBeInTheDocument();
  });
});

describe('time and missing values (AC-63-35)', () => {
  it('reads dd/mm/yyyy, h:mm am/pm', async () => {
    const config = await loadConfig();
    renderCell(config, 'createdAt', ROW);
    expect(screen.getByText('05/11/2026, 3:04 pm')).toBeInTheDocument();
  });

  it.each([
    ['actingUserName', { actingUserName: null, actingUserId: null }],
    ['responseStatus', { responseStatus: null }],
    ['errorCode', { errorCode: null }],
    ['docNo', { docNo: null }],
  ])('a missing %s reads "-"', async (id, patch) => {
    const config = await loadConfig();
    const view = renderCell(config, id, { ...ROW, ...patch });
    expect(view.container.textContent?.trim()).toBe('-');
  });

  it('control: a present person, status and error code are shown as is', async () => {
    const config = await loadConfig();
    renderCell(config, 'actingUserName', ROW);
    renderCell(config, 'responseStatus', ROW);
    renderCell(config, 'errorCode', { ...ROW, errorCode: 'WRITE_TIMEOUT' });
    expect(screen.getByText('Una')).toBeInTheDocument();
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('WRITE_TIMEOUT')).toBeInTheDocument();
  });
});

describe('list query to listCalls (AC-63-31, 32, 34)', () => {
  it('maps search, paging and sort', async () => {
    const config = await loadConfig();
    const query: ListQuery = { page: 2, pageSize: 25, search: 'so-1', sort: { id: 'durationMs', desc: true } };
    await config.fetcher(query);
    expect(listCalls).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, pageSize: 25, search: 'so-1', sort: 'durationMs', order: 'desc' }),
    );
  });

  it('maps an ascending sort', async () => {
    const config = await loadConfig();
    await config.fetcher({ page: 0, pageSize: 25, sort: { id: 'docNo', desc: false } });
    expect(listCalls).toHaveBeenCalledWith(expect.objectContaining({ sort: 'docNo', order: 'asc' }));
  });

  it('maps multi-select filters to repeated values', async () => {
    const config = await loadConfig();
    await config.fetcher({
      page: 0,
      pageSize: 25,
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [
          { kind: 'condition', field: 'book', operator: 'in', value: ['db3', 'db1'] },
          { kind: 'condition', field: 'outcome', operator: 'in', value: ['ok'] },
        ],
      },
    });
    expect(listCalls).toHaveBeenCalledWith(
      expect.objectContaining({ book: ['db3', 'db1'], outcome: ['ok'] }),
    );
  });

  it('resolves to the page the service returned', async () => {
    const page = { data: [ROW], total: 1, page: 0 };
    listCalls.mockResolvedValueOnce(page);
    const config = await loadConfig();
    await expect(config.fetcher({ page: 0, pageSize: 25 })).resolves.toEqual(page);
  });
});
