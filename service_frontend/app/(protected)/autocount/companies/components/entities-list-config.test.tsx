import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig, AutocountSourceKind } from '@/types/autocount';
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
    etlStatus: 'draft',
    ...over,
  };
}

const onSync = vi.fn();
const onEditLookback = vi.fn();
const onRefetch = vi.fn();
const onConfigureMapping = vi.fn();
const onConfigureTask = vi.fn();

function config(
  entities: AutocountEntityConfig[],
  companyActive = true,
  sourceKind: AutocountSourceKind = 'api',
) {
  return renderHook(() =>
    useAutocountEntitiesListConfig({
      entities,
      companyActive,
      sourceKind,
      onSync,
      onEditLookback,
      onRefetch,
      onConfigureMapping,
      onConfigureTask,
    }),
  ).result.current;
}

beforeEach(() => {
  onSync.mockReset();
  onEditLookback.mockReset();
  onRefetch.mockReset();
  onConfigureMapping.mockReset();
  onConfigureTask.mockReset();
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
    // Plan 22 S2: where the entity reads from is visible on the row.
    expect(ids).toContain('sourceImpl');
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

  it('offers "Re-fetch history" ONLY once superseded, as an explicit (un-confirmed) reset (fix round 1, T5, item 15 - a re-sync needs no confirm)', () => {
    const c = config([entity({ watermarkAt: '2026-07-12T00:00:00Z' })]);
    const refetch = c.actions.find((a) => a.id === 'refetch-history')!;
    expect(refetch.permission).toBe('autocount.companies.manage');
    // The mirror image of edit-lookback - visible only when the window is spent.
    expect(refetch.isVisible?.([entity({ watermarkAt: '2026-07-12T00:00:00Z' })])).toBe(true);
    expect(refetch.isVisible?.([entity({ watermarkAt: null })])).toBe(false);
    // Explicit but no confirm dialog - a re-sync widens a read window, it
    // doesn't delete or detach anything.
    expect(refetch.confirm).toBeUndefined();
    const row = entity({ watermarkAt: '2026-07-12T00:00:00Z' });
    refetch.run?.([row], { reload: vi.fn() });
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

describe('entity source (sprint-5/08 D13 - "Configure source" replaces the old task action + the "Change source" dialog)', () => {
  it('offers "Configure source" on EVERY row regardless of its current impl - the Source tab is the one place to change it', () => {
    const c = config([entity()]);
    const task = c.actions.find((a) => a.id === 'configure-task')!;
    expect(task.permission).toBe('autocount.companies.manage');
    expect(task.label).toBe('Configure source');
    expect(task.isVisible).toBeUndefined();
    const row = entity({ sourceImpl: 'sql_db' });
    task.run([row], { reload: vi.fn() });
    expect(onConfigureTask).toHaveBeenCalledWith(row);
  });

  it('has no "change-source" action any more (removed with entity-source-dialog.tsx)', () => {
    const c = config([entity()]);
    expect(c.actions.find((a) => a.id === 'change-source')).toBeUndefined();
  });
});

describe('DB company - API-only actions hidden (plan sprint-5/01, AC-01-18)', () => {
  const dbRow = entity({ entityType: 'customer', sourceImpl: 'sql_db', watermarkAt: null });

  it('never offers "Edit first-run window" on a DB company', () => {
    const c = config([dbRow], true, 'db');
    const edit = c.actions.find((a) => a.id === 'edit-lookback')!;
    // Even before the first sync (where an API row WOULD offer the window edit).
    expect(edit.isVisible?.([dbRow])).toBe(false);
  });

  it('keeps configure-task, sync-now, configure-mapping and refetch-history on a DB company', () => {
    const synced = { ...dbRow, watermarkAt: '2026-08-30T00:00:00Z' };
    const c = config([synced], true, 'db');
    const ids = c.actions.map((a) => a.id);
    expect(ids).toEqual(
      expect.arrayContaining(['configure-task', 'sync-now', 'configure-mapping', 'refetch-history']),
    );
    expect(c.actions.find((a) => a.id === 'refetch-history')!.isVisible?.([synced])).toBe(true);
    expect(c.actions.find((a) => a.id === 'configure-mapping')!.isVisible).toBeUndefined();
    expect(c.actions.find((a) => a.id === 'sync-now')!.isDisabled?.([synced])).toBe(false);
  });

  it("an open (http) company also never offers Edit first-run window (sprint-5/08, AC-08-10)", () => {
    const httpRow = entity({ entityType: 'product', sourceImpl: 'autocount_http', watermarkAt: null });
    const c = config([httpRow], true, 'http');
    expect(c.actions.find((a) => a.id === 'edit-lookback')!.isVisible?.([httpRow])).toBe(false);
  });

  it('an API company\'s rows are unchanged (regression pin)', () => {
    const apiRow = entity({ watermarkAt: null });
    const c = config([apiRow], true, 'api');
    expect(c.actions.find((a) => a.id === 'edit-lookback')!.isVisible?.([apiRow])).toBe(true);
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

// fix/db-company-seed-source: a DB company can carry a row stranded on the
// vendor-API source (seeded before the seed followed the source kind). Since
// sprint-5/08 D13, "Configure source" (always visible, every row) is the ONE
// way out - it opens the row's task editor Source tab regardless of the
// row's current impl, replacing the old per-row "Change source" dialog.
describe('DB company - "Configure source" is per row, reaches a stranded API-sourced row too', () => {
  const stranded = entity({ entityType: 'customer', sourceImpl: 'autocount_read', watermarkAt: null });
  const dbSourced = entity({ entityType: 'supplier', sourceImpl: 'sql_db', watermarkAt: null });

  it('opens the task editor from a DB company row still at autocount_read', () => {
    const c = config([stranded, dbSourced], true, 'db');
    const task = c.actions.find((a) => a.id === 'configure-task')!;
    task.run([stranded], { reload: vi.fn() });
    expect(onConfigureTask).toHaveBeenCalledWith(stranded);
  });

  it('opens the task editor from a DB company row already at sql_db too', () => {
    const c = config([stranded, dbSourced], true, 'db');
    const task = c.actions.find((a) => a.id === 'configure-task')!;
    task.run([dbSourced], { reload: vi.fn() });
    expect(onConfigureTask).toHaveBeenCalledWith(dbSourced);
  });
});
