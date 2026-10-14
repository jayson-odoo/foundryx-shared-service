import { describe, expect, it } from 'vitest';
import type { Idea } from '@/types/ideation';
import {
  MERGE_ROWS,
  canSubmitMerge,
  combineMergeValue,
  defaultMergeChoices,
  mergeFieldsPayload,
  toggleMergeChoice,
} from './idea-merge';

const base: Idea = {
  id: 'x',
  productId: 'p',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: '',
  rawText: '',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-10-06T00:38:00Z',
  isTest: false,
};

const a: Idea = {
  ...base,
  id: 'a',
  ideaNumber: 'IDEA-0010',
  title: 'Order status tracking for dealers',
  problem: 'Dealers cannot track the status after they place an order.',
  rawText: 'dealer want to have a function to track the status after they place order',
};
const b: Idea = {
  ...base,
  id: 'b',
  ideaNumber: 'IDEA-0004',
  title: 'Dealer portal',
  problem: 'No self-service order view',
  desiredOutcome: 'Self-service status',
  useCases: ['Check shipping', 'Reorder'],
};
const c: Idea = { ...base, id: 'c', ideaNumber: 'IDEA-0017', problem: 'Ship notice', useCases: ['Check shipping'] };
const row = (key: string) => MERGE_ROWS.find((r) => r.key === key)!;

describe('idea-merge (plan 20, AC-20-16)', () => {
  it('defaults to the kept cell, else the first non-empty column, else no tick', () => {
    const choices = defaultMergeChoices([a, b, c], 'a');
    expect(choices.title).toEqual(['a']);
    expect(choices.desiredOutcome).toEqual(['b']);
    expect(choices.useCases).toEqual(['b']);
    expect(choices.currentWorkaround).toEqual([]);
  });

  it('toggle keeps column order and Merge needs a tick on every row with content', () => {
    let choices = defaultMergeChoices([a, b, c], 'a');
    choices = toggleMergeChoice(choices, 'problem', 'c', ['a', 'b', 'c']);
    choices = toggleMergeChoice(choices, 'problem', 'b', ['a', 'b', 'c']);
    expect(choices.problem).toEqual(['a', 'b', 'c']);
    expect(canSubmitMerge(choices, [a, b, c])).toBe(true);
    choices = toggleMergeChoice(choices, 'title', 'a', ['a', 'b', 'c']);
    expect(canSubmitMerge(choices, [a, b, c])).toBe(false);
  });

  it('payload omits untouched empty rows', () => {
    const payload = mergeFieldsPayload(defaultMergeChoices([a, b], 'a'));
    expect(payload).not.toHaveProperty('currentWorkaround');
    expect(payload.problem).toEqual(['a']);
  });

  it('combine mirrors the server rule', () => {
    expect(combineMergeValue(row('problem'), [a, b])).toBe(
      'Dealers cannot track the status after they place an order.\n\n--- from IDEA-0004 ---\nNo self-service order view',
    );
    expect(combineMergeValue(row('useCases'), [b, c])).toEqual(['Check shipping', 'Reorder']);
    expect(combineMergeValue(row('desiredOutcome'), [a, b])).toBe('Self-service status');
  });
});
