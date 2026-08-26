import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';
import { parseSyncSummary } from '@/types/autocount';
import type { ListQuery } from '@/types/resource';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const { useAutocountEntitiesListConfig } = await import('./use-entities-list-config');

const QUERY: ListQuery = { page: 0, pageSize: 25 };

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'goods_received_note',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'autocount_read',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    ...over,
  };
}

const onSync = vi.fn();
const onEditLookback = vi.fn();
const onRefetch = vi.fn();
const onConfigureMapping = vi.fn();

function config(entities: AutocountEntityConfig[], companyActive = true) {
  return renderHook(() =>
    useAutocountEntitiesListConfig({
      entities,
      companyActive,
      onSync,
      onEditLookback,
      onRefetch,
      onConfigureMapping,
    }),
  ).result.current;
}

beforeEach(() => {
  onSync.mockReset();
  onEditLookback.mockReset();
  onRefetch.mockReset();
  onConfigureMapping.mockReset();
});

describe('entities list config', () => {
  it('is a Resource-shell config, not a hand-rolled table', () => {
    const c = config([entity()]);
    expect(c.viewKey).toBe('autocount.entities.list');
    expect(c.columns.length).toBeGreaterThan(0);
    expect(c.enableStatusViews).toBe(false);
  });

  it('surfaces the delta state the catalogue will need as it grows', () => {
    // The columns that make a zero-record sync explicable rather than silent.
    const ids = config([entity()]).columns.map((col) => col.id);
    expect(ids).toContain('entityType');
    expect(ids).toContain('syncMode');
    expect(ids).toContain('lastSuccessAt');
    expect(ids).toContain('watermarkAt');
    expect(ids).toContain('initialLookbackDays');
    expect(ids).toContain('health');
  });

  it('has no detail page, so a row click never dead-ends', () => {
    expect(config([entity()]).rowHref(entity())).toBe('#');
  });

  it('paginates and searches the in-memory rows', async () => {
    const rows = [
      entity({ id: 'a', entityType: 'goods_received_note' }),
      entity({ id: 'b', entityType: 'purchase_order' }),
    ];
    const c = config(rows);

    const all = await c.fetcher(QUERY);
    expect(all.total).toBe(2);

    const searched = await c.fetcher({ ...QUERY, search: 'purchase' });
    expect(searched.total).toBe(1);
    expect(searched.data[0].id).toBe('b');

    const paged = await c.fetcher({ page: 1, pageSize: 1 });
    expect(paged.data).toHaveLength(1);
    expect(paged.total).toBe(2);
  });
});

describe('entities actions', () => {
  it('gates Sync now behind the run permission and fires for its own row', () => {
    const c = config([entity()]);
    const sync = c.actions.find((a) => a.id === 'sync-now')!;
    expect(sync.permission).toBe('autocount.sync.run');
    sync.run([entity({ entityType: 'goods_received_note' })], { reload: vi.fn() });
    expect(onSync).toHaveBeenCalledWith('goods_received_note');
  });

  it('disables Sync now when it could not succeed', () => {
    // Offered-then-failed is the foolproof-UI violation; disabled is the fix.
    const inactive = config([entity()], false).actions.find((a) => a.id === 'sync-now')!;
    expect(inactive.isDisabled?.([entity()])).toBe(true);

    const disabledEntity = entity({ enabled: false });
    const c = config([disabledEntity]).actions.find((a) => a.id === 'sync-now')!;
    expect(c.isDisabled?.([disabledEntity])).toBe(true);
    expect(c.isDisabled?.([entity()])).toBe(false);
  });

  it('gates the first-run window edit behind the manage permission', () => {
    const c = config([entity()]);
    const edit = c.actions.find((a) => a.id === 'edit-lookback')!;
    expect(edit.permission).toBe('autocount.companies.manage');
    const row = entity();
    edit.run([row], { reload: vi.fn() });
    expect(onEditLookback).toHaveBeenCalledWith(row);
  });

  it('offers "Edit first-run window" ONLY before the first sync (no dead dialog)', () => {
    // AC-15-30: once a watermark exists, editing the window is a guaranteed
    // no-op - the action must not be offered (it opened a disabled dialog).
    const c = config([entity()]);
    const edit = c.actions.find((a) => a.id === 'edit-lookback')!;
    expect(edit.isVisible?.([entity({ watermarkAt: null })])).toBe(true);
    expect(edit.isVisible?.([entity({ watermarkAt: '2026-07-12T00:00:00Z' })])).toBe(false);
  });

  it('offers "Re-fetch history" ONLY once superseded, as a confirmed reset', () => {
    const c = config([entity({ watermarkAt: '2026-07-12T00:00:00Z' })]);
    const refetch = c.actions.find((a) => a.id === 'refetch-history')!;
    expect(refetch.permission).toBe('autocount.companies.manage');
    // The mirror image of edit-lookback - visible only when the window is spent.
    expect(refetch.isVisible?.([entity({ watermarkAt: '2026-07-12T00:00:00Z' })])).toBe(true);
    expect(refetch.isVisible?.([entity({ watermarkAt: null })])).toBe(false);
    // Explicit + confirmed, never a silent Days box.
    expect(refetch.confirm).toBeDefined();
    const row = entity({ watermarkAt: '2026-07-12T00:00:00Z' });
    refetch.run([row], { reload: vi.fn() });
    expect(onRefetch).toHaveBeenCalledWith(row);
  });

  it('offers "Configure mapping" gated on manage, opening the editor for its row', () => {
    const c = config([entity()]);
    const mapping = c.actions.find((a) => a.id === 'configure-mapping')!;
    expect(mapping).toBeDefined();
    expect(mapping.permission).toBe('autocount.companies.manage');
    const row = entity();
    mapping.run([row], { reload: vi.fn() });
    expect(onConfigureMapping).toHaveBeenCalledWith(row);
  });
});

describe('sync summary parsing (the zero-record case)', () => {
  it('reads a legitimate empty sync as a successful no-op', () => {
    // The reported symptom: a second Sync now appeared to do nothing. It was
    // correct - the vendor had no changes - and the UI must say so.
    const summary = parseSyncSummary({
      entityType: 'goods_received_note',
      fetched: 0,
      staged: 0,
      failed: 0,
      watermarkAdvancedTo: null,
      awaitingApproval: false,
    });
    expect(summary).not.toBeNull();
    expect(summary!.fetched).toBe(0);
    expect(summary!.failed).toBe(0);
    // Nothing to review - the operator must NOT be routed to a review surface.
    expect(summary!.awaitingApproval).toBe(false);
  });

  it('distinguishes a staged batch from an empty one', () => {
    const staged = parseSyncSummary({ fetched: 2, staged: 2, awaitingApproval: true })!;
    expect(staged.staged).toBe(2);
    expect(staged.awaitingApproval).toBe(true);
  });

  it('reports mapping failures rather than folding them into "nothing"', () => {
    const failed = parseSyncSummary({ fetched: 3, staged: 0, failed: 3 })!;
    expect(failed.fetched).toBe(3);
    expect(failed.failed).toBe(3);
  });

  it('is null when a job has no result yet (queued under a real worker)', () => {
    expect(parseSyncSummary(null)).toBeNull();
    expect(parseSyncSummary(undefined)).toBeNull();
  });

  it('coerces a malformed result rather than rendering NaN', () => {
    const odd = parseSyncSummary({ fetched: 'many', staged: null })!;
    expect(odd.fetched).toBe(0);
    expect(odd.staged).toBe(0);
  });
});
