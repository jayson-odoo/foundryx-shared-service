/**
 * Plan 20 AC-20-16 - the field-level merge dialog: one column per idea, a tick
 * per cell, defaults on the kept idea, Merge disabled while a row with content
 * has no tick, Result preview when combining, radio picks the kept idea.
 * (Replaces the AC-94-22 survivor-picker tests - that UI is gone.)
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import { MergeIdeasDialog } from './merge-ideas-dialog';

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Faster quotation',
  rawText: '',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

const ideas = [
  anIdea({
    id: 'a',
    ideaNumber: 'IDEA-0010',
    title: 'Order status tracking for dealers',
    problem: 'Dealers cannot track the status after they place an order.',
  }),
  anIdea({
    id: 'b',
    ideaNumber: 'IDEA-0004',
    title: 'Dealer portal',
    problem: 'No self-service order view',
    desiredOutcome: 'Self-service status',
  }),
  anIdea({ id: 'c', ideaNumber: 'IDEA-0017', title: 'Ship notice', problem: 'Not told when shipped' }),
];

describe('MergeIdeasDialog (plan 20, AC-20-16)', () => {
  it('renders one column per idea with defaults on the kept idea', () => {
    render(<MergeIdeasDialog ideas={ideas} initialKeptId="a" onClose={vi.fn()} onMerge={vi.fn()} />);
    expect(screen.getByRole('radio', { name: 'Keep IDEA-0010' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Use IDEA-0010 Title' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Use IDEA-0004 Title' })).not.toBeChecked();
    // Kept idea has no desired outcome -> first non-empty column is ticked.
    expect(screen.getByRole('checkbox', { name: 'Use IDEA-0004 Desired outcome' })).toBeChecked();
    // A row with no content anywhere offers no tick.
    const workaround = screen.getByTestId('merge-row-currentWorkaround');
    expect(within(workaround).queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('combines ticked cells with a Result preview and sends the fields map', async () => {
    const user = userEvent.setup();
    const onMerge = vi.fn().mockResolvedValue(undefined);
    render(<MergeIdeasDialog ideas={ideas} initialKeptId="a" onClose={vi.fn()} onMerge={onMerge} />);

    await user.click(screen.getByRole('checkbox', { name: 'Use IDEA-0004 Business problem' }));
    const problemRow = screen.getByTestId('merge-row-problem');
    expect(within(problemRow).getByText('Result')).toBeInTheDocument();
    expect(within(problemRow).getByText(/--- from IDEA-0004 ---/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^merge$/i }));
    expect(onMerge).toHaveBeenCalledWith('a', {
      title: ['a'],
      problem: ['a', 'b'],
      desiredOutcome: ['b'],
    });
  });

  it('disables Merge while a row with content has no tick', async () => {
    const user = userEvent.setup();
    render(<MergeIdeasDialog ideas={ideas} initialKeptId="a" onClose={vi.fn()} onMerge={vi.fn()} />);
    const mergeButton = screen.getByRole('button', { name: /^merge$/i });
    expect(mergeButton).toBeEnabled();
    await user.click(screen.getByRole('checkbox', { name: 'Use IDEA-0010 Title' }));
    expect(mergeButton).toBeDisabled();
  });

  it('the radio changes which idea is kept', async () => {
    const user = userEvent.setup();
    const onMerge = vi.fn().mockResolvedValue(undefined);
    render(<MergeIdeasDialog ideas={ideas} initialKeptId="a" onClose={vi.fn()} onMerge={onMerge} />);
    await user.click(screen.getByRole('radio', { name: 'Keep IDEA-0017' }));
    await user.click(screen.getByRole('button', { name: /^merge$/i }));
    expect(onMerge.mock.calls[0][0]).toBe('c');
  });
});
