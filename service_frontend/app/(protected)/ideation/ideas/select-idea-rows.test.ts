/**
 * Plan 15 (AC-15-01/02/05/08/09) - `selectIdeaRows` owns filter + sort + the
 * default net-vote order, so the list fetcher AND the detail pager walk the
 * same rows. Written test-first: the current helper ignores `filter`/`sort`.
 */
import { describe, expect, it } from 'vitest';
import type { Idea, IdeaAttachment } from '@/types/ideation';
import type { FilterGroup, ListQuery } from '@/types/resource';
import { selectIdeaRows } from './select-idea-rows';

type Query = Parameters<typeof selectIdeaRows>[1];

const anIdea = (over: Partial<Idea> = {}): Idea =>
  ({
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
    statusLabel: 'New',
    statusIsArchived: false,
    ...over,
  }) as Idea;

const q = (over: Partial<Query> = {}): Query => ({ search: '', statusView: 'active', ...over });
const ids = (rows: Idea[]) => rows.map((r) => r.id);

const group = (
  field: string,
  operator: 'in' | 'eq',
  value: string | string[],
): FilterGroup => ({
  kind: 'group',
  combinator: 'and',
  rules: [{ kind: 'condition', field, operator, value }],
});

describe('selectIdeaRows - default order (AC-15-08, amended by AC-19-17)', () => {
  it('ranks by UPVOTES desc, ignoring any stale downvotes (up5/down4 above up2/down0)', () => {
    const rows = selectIdeaRows(
      [
        anIdea({ id: 'up2', upvotes: 2, downvotes: 0 }),
        anIdea({ id: 'up5', upvotes: 5, downvotes: 4 }),
      ],
      q(),
    );
    expect(ids(rows)).toEqual(['up5', 'up2']);
  });

  it('breaks an upvote tie by createdAt desc (newest first)', () => {
    const rows = selectIdeaRows(
      [
        anIdea({ id: 'low', upvotes: 1, createdAt: '2026-07-20T00:00:00Z' }),
        anIdea({ id: 'tieOld', upvotes: 3, downvotes: 9, createdAt: '2026-07-01T00:00:00Z' }),
        anIdea({ id: 'tieNew', upvotes: 3, downvotes: 0, createdAt: '2026-07-10T00:00:00Z' }),
      ],
      q(),
    );
    expect(ids(rows)).toEqual(['tieNew', 'tieOld', 'low']);
  });

  it('the Votes column sort is by upvotes too, ties by createdAt desc', () => {
    const ideas = [
      anIdea({ id: 'a', upvotes: 1, downvotes: 0, createdAt: '2026-07-01T00:00:00Z' }),
      anIdea({ id: 'b', upvotes: 6, downvotes: 6, createdAt: '2026-07-02T00:00:00Z' }),
      anIdea({ id: 'c', upvotes: 6, downvotes: 0, createdAt: '2026-07-03T00:00:00Z' }),
    ];
    expect(ids(selectIdeaRows(ideas, q({ sort: { id: 'votes', desc: true } })))).toEqual(['c', 'b', 'a']);
  });
});

describe('selectIdeaRows - filter (AC-15-01/02)', () => {
  const ideas = [
    anIdea({ id: 'a', status: 'captured', submitterName: 'Jayson' }),
    anIdea({ id: 'b', status: 'discussed', submitterName: 'Alice' }),
    anIdea({ id: 'c', status: 'discussed', submitterName: 'Jayson' }),
  ];

  it('status `in` keeps only the matching status KEY', () => {
    const rows = selectIdeaRows(ideas, q({ filter: group('status', 'in', ['discussed']) }));
    expect(ids(rows).sort()).toEqual(['b', 'c']);
  });

  it('submitter `eq` narrows to that submitterName', () => {
    const rows = selectIdeaRows(ideas, q({ filter: group('submitter', 'eq', 'Alice') }));
    expect(ids(rows)).toEqual(['b']);
  });

  it('search still narrows alongside the filter, and the archived split is unchanged', () => {
    const withArchived = [
      ...ideas,
      anIdea({ id: 'z', status: 'discussed', statusIsArchived: true, problem: 'Export archived' }),
    ];
    expect(ids(selectIdeaRows(withArchived, q({ search: 'export archived' })))).toEqual([]);
    expect(ids(selectIdeaRows(withArchived, q({ search: 'export archived', statusView: 'trashed' })))).toEqual(['z']);
    const both = selectIdeaRows(withArchived, q({ search: 'jayson', filter: group('status', 'in', ['discussed']) }));
    expect(ids(both)).toEqual(['c']);
  });
});

describe('selectIdeaRows - channel + submitted filters', () => {
  it('channel `in` keeps only that source', () => {
    const ideas = [
      anIdea({ id: 'w', source: 'whatsapp' }),
      anIdea({ id: 'm', source: 'manual' }),
    ];
    expect(ids(selectIdeaRows(ideas, q({ filter: group('channel', 'in', ['whatsapp']) })))).toEqual(['w']);
  });

  it('submitted `after` a date keeps only later ideas', () => {
    const ideas = [
      anIdea({ id: 'old', createdAt: '2026-06-01T00:00:00Z' }),
      anIdea({ id: 'new', createdAt: '2026-08-01T00:00:00Z' }),
    ];
    const rows = selectIdeaRows(
      ideas,
      q({
        filter: {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', field: 'submitted', operator: 'after', value: '2026-07-01' }],
        },
      }),
    );
    expect(ids(rows)).toEqual(['new']);
  });
});

describe('selectIdeaRows - sort (AC-05)', () => {
  it('votes sorts NUMERICALLY (10 after 9, never string order)', () => {
    const ideas = [
      anIdea({ id: 'ten', upvotes: 10 }),
      anIdea({ id: 'nine', upvotes: 9 }),
      anIdea({ id: 'two', upvotes: 2 }),
    ];
    expect(ids(selectIdeaRows(ideas, q({ sort: { id: 'votes', desc: false } })))).toEqual(['two', 'nine', 'ten']);
    expect(ids(selectIdeaRows(ideas, q({ sort: { id: 'votes', desc: true } })))).toEqual(['ten', 'nine', 'two']);
  });

  it('submitted sorts by createdAt as a date', () => {
    const ideas = [
      anIdea({ id: 'mid', createdAt: '2026-07-10T00:00:00Z' }),
      anIdea({ id: 'new', createdAt: '2026-08-01T00:00:00Z' }),
      anIdea({ id: 'old', createdAt: '2026-06-30T00:00:00Z' }),
    ];
    expect(ids(selectIdeaRows(ideas, q({ sort: { id: 'submitted', desc: true } })))).toEqual(['new', 'mid', 'old']);
  });
});

describe('types - IdeaAttachment.contentPath (AC-15-19)', () => {
  it('accepts a contentPath string or null', () => {
    const withPath: IdeaAttachment = {
      id: 'a',
      kind: 'image',
      name: 'x.png',
      url: '',
      contentPath: '/ideation/ideas/i/attachments/a/content',
    };
    const withNull: IdeaAttachment = { ...withPath, contentPath: null };
    expect(withPath.contentPath).toContain('/content');
    expect(withNull.contentPath).toBeNull();
  });
});

// Compile-time guard that the query shape the pager passes is accepted.
const _queryShape: Pick<ListQuery, 'search' | 'statusView' | 'filter' | 'sort'> = q();
void _queryShape;
