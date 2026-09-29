import { describe, expect, it, vi } from 'vitest';
import { cleanup, render, renderHook, screen } from '@testing-library/react';
import type { Idea } from '@/types/ideation';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { useIdeasListConfig } from './use-ideas-list-config';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v.slice(0, 10),
    formatDateTime: (v: string) => v.slice(0, 10),
    formatTime: (v: string) => v.slice(11, 16),
  }),
}));

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  // AC-94 (issue #94, ideation round 2) additions - engine-driven display +
  // merge bookkeeping. Defaults match a plain, un-merged "New" idea.
  statusId: 'idea-status-captured',
  statusLabel: 'New',
  statusColor: 'blue',
  statusIsArchived: false,
  transitions: [
    { id: 'idea-tr-triage', label: 'Triage', toStatusId: 'idea-status-triaged', toStatusLabel: 'Triaged' },
  ],
  advanceTransitionId: 'idea-tr-triage',
  rank: 1,
  mergedIntoId: null,
  mergedInto: null,
  mergedCount: 0,
  ...over,
} as Idea);

const handlers = () => ({
  onCreate: vi.fn(),
  onVote: vi.fn(),
  onAdvance: vi.fn(),
  onRestore: vi.fn(),
  onDelete: vi.fn(),
  onReorder: vi.fn(),
  onPromote: vi.fn(),
  onMerge: vi.fn(),
  onUnmerge: vi.fn(),
});

function config(ideas: Idea[]) {
  const { result } = renderHook(() => useIdeasListConfig(ideas, handlers()));
  return result.current;
}

function embedConfig(ideas: Idea[]) {
  const { result } = renderHook(() => useIdeasListConfig(ideas, handlers()), {
    wrapper: ({ children }) => (
      <IdeationRuntimeProvider
        runtime={{
          mode: 'embed',
          service: ideationEmbedService,
          paths: { listHref: '/embed/ideas', formHref: (id) => `/embed/ideas/${id}`, newHref: '/embed/ideas/new' },
        }}
      >
        {children}
      </IdeationRuntimeProvider>
    ),
  });
  return result.current;
}

// ── issue #1179 - Promote to BR foolproof-disable on a test idea ──────────────

describe('useIdeasListConfig - promote-br action', () => {
  it('is NOT disabled for a same-product selection of real ideas', () => {
    const cfg = config([anIdea()]);
    const promote = cfg.actions.find((a) => a.id === 'promote-br')!;
    expect(promote.isDisabled?.([anIdea({ id: 'a' }), anIdea({ id: 'b' })])).toBe(false);
  });

  // AC-90-311 (issue #90 owner ruling 26 Sep ~12:50Z, INVERTS the old
  // "is disabled when any selected row is a test idea" - REWRITTEN, not
  // deleted, per the #90 lane brief): a test idea may now be promoted to a
  // TEST Business Requirement, so an all-test selection is enabled; only a
  // MIXED test+real selection stays disabled (a promote lane cannot be
  // mixed, same principle as the mixed-product rule).
  it('is disabled for a MIXED test+real selection, but not for an all-test selection', () => {
    const cfg = config([anIdea()]);
    const promote = cfg.actions.find((a) => a.id === 'promote-br')!;
    expect(
      promote.isDisabled?.([anIdea({ id: 'a' }), anIdea({ id: 'b', isTest: true })]),
    ).toBe(true);
    // A lone test idea, or an all-test selection, is NOT disabled.
    expect(promote.isDisabled?.([anIdea({ id: 'a', isTest: true })])).toBe(false);
    expect(
      promote.isDisabled?.([
        anIdea({ id: 'a', isTest: true }),
        anIdea({ id: 'b', isTest: true }),
      ]),
    ).toBe(false);
  });
});

// ── issue #1179 - TEST badge on the idea column ────────────────────────────────

describe('useIdeasListConfig - Idea column TEST badge', () => {
  it('renders the TEST badge for an isTest row', () => {
    const cfg = config([anIdea({ isTest: true })]);
    const column = cfg.columns.find((c) => c.id === 'problem')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: anIdea({ isTest: true }) } })}</>);
    expect(screen.getByText('TEST')).toBeInTheDocument();
    expect(screen.getByText('Export orders to Excel')).toBeInTheDocument();
  });

  it('does not render the TEST badge for a real row', () => {
    const cfg = config([anIdea()]);
    const column = cfg.columns.find((c) => c.id === 'problem')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: anIdea({ isTest: false }) } })}</>);
    expect(screen.queryByText('TEST')).not.toBeInTheDocument();
  });
});

// ── AC-94-21 - Merge in the bulk Actions menu ──────────────────────────────────
// TEST-FIRST: there is no `merge` action yet - `cfg.actions.find` returns
// `undefined` and every `?.` below silently no-ops, so `toBe(false)`/`toBe(true)`
// assertions fail until slice S1 adds the action.

describe('useIdeasListConfig - merge visibility (AC-94-21)', () => {
  it('is hidden with 0 or 1 selected, shown with 2+', () => {
    const cfg = config([anIdea({ id: 'a' }), anIdea({ id: 'b' })]);
    const merge = cfg.actions.find((a) => a.id === 'merge')!;
    expect(merge).toBeDefined();
    expect(merge.isVisible?.([anIdea({ id: 'a' })])).toBe(false);
    expect(merge.isVisible?.([anIdea({ id: 'a' }), anIdea({ id: 'b' })])).toBe(true);
  });

  it('is disabled on a mixed-product or mixed test/real selection', () => {
    const cfg = config([anIdea()]);
    const merge = cfg.actions.find((a) => a.id === 'merge')!;
    expect(
      merge.isDisabled?.([anIdea({ id: 'a', productId: 'p1' }), anIdea({ id: 'b', productId: 'p2' })]),
    ).toBe(true);
    expect(
      merge.isDisabled?.([anIdea({ id: 'a', isTest: false }), anIdea({ id: 'b', isTest: true })]),
    ).toBe(true);
    expect(
      merge.isDisabled?.([anIdea({ id: 'a', productId: 'p1' }), anIdea({ id: 'b', productId: 'p1' })]),
    ).toBe(false);
  });

  it('is hidden when any selected row is archived', () => {
    const cfg = config([anIdea()]);
    const merge = cfg.actions.find((a) => a.id === 'merge')!;
    expect(
      merge.isVisible?.([anIdea({ id: 'a' }), anIdea({ id: 'b', statusIsArchived: true } as Partial<Idea>)]),
    ).toBe(false);
  });

  it('is gated by ideation.triage.manage ONLY on the operator surface (the embed has no session)', () => {
    const operatorCfg = config([anIdea()]);
    const operatorMerge = operatorCfg.actions.find((a) => a.id === 'merge')!;
    expect(operatorMerge.permission).toBe('ideation.triage.manage');

    const embedCfg = embedConfig([anIdea()]);
    const embedMerge = embedCfg.actions.find((a) => a.id === 'merge')!;
    expect(embedMerge.permission).toBeUndefined();
  });
});

// ── AC-94-23 - merged count badge ───────────────────────────────────────────────

describe('useIdeasListConfig - merged badge (AC-94-23)', () => {
  it('shows "{n} merged" on a survivor, nothing on a plain idea', () => {
    const cfg = config([anIdea()]);
    const column = cfg.columns.find((c) => c.id === 'problem')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;

    render(<>{cell({ row: { original: anIdea({ mergedCount: 2 }) } })}</>);
    expect(screen.getByText('2 merged')).toBeInTheDocument();
    cleanup(); // unmount before the next render - else the "2 merged" badge
    // above is still in the document when the query below runs.

    render(<>{cell({ row: { original: anIdea({ mergedCount: 0 }) } })}</>);
    expect(screen.queryByText(/merged/)).not.toBeInTheDocument();
  });
});

// ── AC-94-24 - list Unmerge on a survivor ───────────────────────────────────────

describe('useIdeasListConfig - unmerge visibility (AC-94-24)', () => {
  it('is shown for one or more survivors, hidden if any selected row has mergedCount 0', () => {
    const cfg = config([anIdea()]);
    const unmerge = cfg.actions.find((a) => a.id === 'unmerge')!;
    expect(unmerge).toBeDefined();
    expect(unmerge.isVisible?.([anIdea({ id: 'a', mergedCount: 2 })])).toBe(true);
    expect(
      unmerge.isVisible?.([anIdea({ id: 'a', mergedCount: 2 }), anIdea({ id: 'b', mergedCount: 0 })]),
    ).toBe(false);
  });

  it('calls unmerge(id) per survivor via the onUnmerge handler', async () => {
    const onUnmerge = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useIdeasListConfig([anIdea()], { ...handlers(), onUnmerge }),
    );
    const unmerge = result.current.actions.find((a) => a.id === 'unmerge')!;
    const rows = [anIdea({ id: 'a', mergedCount: 1 }), anIdea({ id: 'b', mergedCount: 2 })];
    await unmerge.run?.(rows, { reload: vi.fn() });
    expect(onUnmerge).toHaveBeenCalledWith('a');
    expect(onUnmerge).toHaveBeenCalledWith('b');
  });
});

// ── AC-94-47 - list order is the server's order ─────────────────────────────────

describe('useIdeasListConfig - server order (AC-94-47)', () => {
  it('keeps the given order - no client-side priority sort', async () => {
    // Deliberately NOT priority-ascending - if the config still `.sort()`s by
    // `priority`, the fetched order will NOT match this input order.
    const ideas = [
      anIdea({ id: 'c', priority: 2 }),
      anIdea({ id: 'a', priority: 0 }),
      anIdea({ id: 'b', priority: 1 }),
    ];
    const cfg = config(ideas);
    const { data } = await cfg.fetcher({ page: 0, pageSize: 10, search: '', statusView: 'active' } as never);
    expect(data.map((r) => r.id)).toEqual(['c', 'a', 'b']);
  });
});

// ── AC-94-56 - labels and colours render from the API ───────────────────────────

describe('useIdeasListConfig - status from API (AC-94-56)', () => {
  it('renders the Status column from statusLabel (form shows no status, AC-94-33)', () => {
    const cfg = config([anIdea()]);
    const column = cfg.columns.find((c) => c.id === 'status')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    render(<>{cell({ row: { original: anIdea({ statusLabel: 'Discussed', statusColor: 'indigo' }) } })}</>);
    expect(screen.getByText('Discussed')).toBeInTheDocument();
  });

  it('the CSV export writes the label, not the raw key', async () => {
    const cfg = config([anIdea({ statusLabel: 'Discussed' })]);
    const csv = await cfg.exporter!({ page: 0, pageSize: 10, search: '', statusView: 'active' } as never, []);
    expect(csv).toContain('Discussed');
  });
});

// ── AC-94-57 - Advance to next stage (row, form, bulk) ──────────────────────────

describe('useIdeasListConfig - advance (AC-94-57)', () => {
  it('labels "Move to {label}" when every row targets the same label, else generic', () => {
    const cfg = config([anIdea()]);
    const advance = cfg.actions.find((a) => a.id === 'advance')!;
    const sameTarget = [
      anIdea({ id: 'a', advanceTransitionId: 'tr-1', transitions: [{ id: 'tr-1', label: 'Triage', toStatusId: 's', toStatusLabel: 'Triaged' }] }),
      anIdea({ id: 'b', advanceTransitionId: 'tr-1', transitions: [{ id: 'tr-1', label: 'Triage', toStatusId: 's', toStatusLabel: 'Triaged' }] }),
    ] as Idea[];
    expect(typeof advance.label === 'function' ? advance.label(sameTarget) : advance.label).toBe('Move to Triaged');

    const mixedTarget = [
      anIdea({ id: 'a', advanceTransitionId: 'tr-1', transitions: [{ id: 'tr-1', label: 'Triage', toStatusId: 's', toStatusLabel: 'Triaged' }] }),
      anIdea({ id: 'b', advanceTransitionId: 'tr-2', transitions: [{ id: 'tr-2', label: 'Link', toStatusId: 's2', toStatusLabel: 'Linked to BR' }] }),
    ] as Idea[];
    expect(typeof advance.label === 'function' ? advance.label(mixedTarget) : advance.label).toBe(
      'Advance to next stage',
    );
  });

  it('is disabled when any row has no advanceTransitionId (a terminal status)', () => {
    const cfg = config([anIdea()]);
    const advance = cfg.actions.find((a) => a.id === 'advance')!;
    expect(
      advance.isDisabled?.([anIdea({ id: 'a', advanceTransitionId: null } as Partial<Idea>)]),
    ).toBe(true);
  });

  it('fires each row\'s OWN edge via onAdvance, never a hardcoded key', async () => {
    const onAdvance = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useIdeasListConfig([anIdea()], { ...handlers(), onAdvance }));
    const advance = result.current.actions.find((a) => a.id === 'advance')!;
    const row = anIdea({
      id: 'a',
      advanceTransitionId: 'tr-1',
      transitions: [{ id: 'tr-1', label: 'Triage', toStatusId: 'idea-status-triaged', toStatusLabel: 'Triaged' }],
    }) as Idea;
    await advance.run?.([row], { reload: vi.fn() });
    expect(onAdvance).toHaveBeenCalledWith(row);
  });
});

// ── AC-94-60 (BE half in test_ideation_status_display.py) - Archived view ──────

describe('useIdeasListConfig - archived view (AC-94-60, red first)', () => {
  it('an archived idea (statusIsArchived) shows in the Archived view even under a RENAMED status key', async () => {
    // A tenant that renamed "Triaged" -> "Discussed" (D7 fork) never changes
    // the KEY - only `statusIsArchived` (a trait flag) may be relied on, never
    // `status === 'archived'` (a hardcoded key).
    const archived = anIdea({ id: 'a', status: 'archived-renamed-key', statusIsArchived: true } as Partial<Idea>);
    const cfg = config([archived]);
    const { data } = await cfg.fetcher({
      page: 0,
      pageSize: 10,
      search: '',
      statusView: 'trashed',
    } as never);
    expect(data.map((r) => r.id)).toContain('a');
  });
});

// ── Plan 15 (AC-15-04..08, 11) - filters / sort / columns / vote order ─────────

describe('useIdeasListConfig - plan 15 list shape', () => {
  it('has no manual reorder (AC-15-07)', () => {
    expect(config([anIdea()]).rowReorder).toBeUndefined();
  });

  it('defaults to Votes desc (AC-15-08)', () => {
    expect(config([anIdea()]).defaultSort).toEqual({ id: 'votes', desc: true });
  });

  it('offers a Status enum built from the loaded ideas labels, and a Submitter enum (AC-15-01/02)', () => {
    const cfg = config([
      anIdea({ id: 'a', status: 'captured', statusLabel: 'New', submitterName: 'Jayson' }),
      anIdea({ id: 'b', status: 'discussed', statusLabel: 'Discussed', submitterName: 'Alice' }),
      anIdea({ id: 'c', status: 'discussed', statusLabel: 'Discussed', submitterName: 'Jayson' }),
    ]);
    const status = cfg.filterFields.find((f) => f.field === 'status')!;
    expect(status.type).toBe('enum');
    expect(status.options).toEqual(
      expect.arrayContaining([
        { label: 'New', value: 'captured' },
        { label: 'Discussed', value: 'discussed' },
      ]),
    );
    expect(status.options).toHaveLength(2);
    const submitter = cfg.filterFields.find((f) => f.field === 'submitter')!;
    expect(submitter.type).toBe('enum');
    expect((submitter.options ?? []).map((o) => o.value).sort()).toEqual(['Alice', 'Jayson']);
  });

  it('has a Submitted column and every data column is sortable with a headerTitle (AC-15-03/04/05)', () => {
    const cfg = config([anIdea()]);
    const ids = cfg.columns.map((c) => c.id);
    expect(ids).toContain('submitted');
    const dataCols = cfg.columns.filter((c) => !['select', 'actions'].includes(String(c.id)));
    expect(dataCols.length).toBeGreaterThanOrEqual(6);
    for (const c of dataCols) {
      expect(c.enableSorting, `${c.id} sortable`).not.toBe(false);
      expect(c.meta?.headerTitle, `${c.id} headerTitle`).toBeTruthy();
    }
  });

  it('the Submitted cell formats createdAt, not the raw ISO string (AC-15-03)', () => {
    const cfg = config([anIdea()]);
    const column = cfg.columns.find((c) => c.id === 'submitted')!;
    const cell = column.cell as (ctx: unknown) => React.ReactNode;
    const { container } = render(<>{cell({ row: { original: anIdea() } })}</>);
    expect(container.textContent).toMatch(/2026/);
    expect(container.textContent).not.toContain('2026-07-18T00:00:00Z');
  });

  it('operator has a Product column, embed does not (AC-15-06)', () => {
    expect(config([anIdea()]).columns.map((c) => c.id)).toContain('product');
    expect(embedConfig([anIdea()]).columns.map((c) => c.id)).not.toContain('product');
  });

  it('the CSV header row includes Submitted (AC-15-11)', async () => {
    const cfg = config([anIdea()]);
    const csv = await cfg.exporter!({ page: 0, pageSize: 10, search: '', statusView: 'active' } as never, []);
    expect(csv.split('\n')[0]).toContain('Submitted');
  });

  it('the fetcher applies the default net-vote order and the filter (AC-15-08/01)', async () => {
    const ideas = [
      anIdea({ id: 'net1', upvotes: 5, downvotes: 4 }),
      anIdea({ id: 'net2', upvotes: 2, downvotes: 0, status: 'discussed' }),
    ];
    const cfg = config(ideas);
    const base = { page: 0, pageSize: 10, search: '', statusView: 'active' } as never;
    const { data } = await cfg.fetcher(base);
    expect(data.map((r) => r.id)).toEqual(['net2', 'net1']);
    const filtered = await cfg.fetcher({
      page: 0,
      pageSize: 10,
      search: '',
      statusView: 'active',
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', field: 'status', operator: 'in', value: ['discussed'] }],
      },
    } as never);
    expect(filtered.data.map((r) => r.id)).toEqual(['net2']);
  });
});

describe('useIdeasListConfig - embed promote (AC-15-24)', () => {
  it('shows the embed Promote action ungated (no permission key); operator stays gated', () => {
    const embedPromote = embedConfig([anIdea()]).actions.find((a) => a.id === 'promote-br')!;
    expect(embedPromote.permission).toBeUndefined();
    const opPromote = config([anIdea()]).actions.find((a) => a.id === 'promote-br')!;
    expect(opPromote.permission).toBe('ideation.business_requirements.manage');
  });
});
