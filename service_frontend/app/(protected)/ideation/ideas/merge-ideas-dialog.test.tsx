/**
 * AC-94-22 (issue #94, ideation round 2) - the survivor picker is the system
 * dropdown: a dialog with a `SearchSelect` whose options are EXACTLY the
 * selected ideas (idea number + title), no default pick, Merge disabled
 * until one is chosen, and no other select control rendered (plan section
 * 3.5, owner rule: every select is `SearchSelect`/`MultiSelect`).
 *
 * TEST-FIRST (PRINCIPLES.md): `./merge-ideas-dialog` doesn't exist yet -
 * fails with a module-not-found error until slice S1 lands.
 */
import { render, screen } from '@testing-library/react';
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
  ideaNumber: 'IDEA-0012',
  ...over,
});

describe('MergeIdeasDialog (AC-94-22)', () => {
  it('lists exactly the selected ideas as options, no default pick, Merge disabled', async () => {
    const user = userEvent.setup();
    const ideas = [
      anIdea({ id: 'a', ideaNumber: 'IDEA-0012', problem: 'Faster quotation' }),
      anIdea({ id: 'b', ideaNumber: 'IDEA-0013', problem: 'Faster quote generator' }),
    ];
    render(<MergeIdeasDialog ideas={ideas} onClose={vi.fn()} onMerge={vi.fn()} />);

    const mergeButton = screen.getByRole('button', { name: /^merge$/i });
    expect(mergeButton).toBeDisabled(); // no default pick

    const combobox = screen.getByRole('combobox');
    await user.click(combobox);
    expect(await screen.findByText(/IDEA-0012.*Faster quotation/i)).toBeInTheDocument();
    expect(await screen.findByText(/IDEA-0013.*Faster quote generator/i)).toBeInTheDocument();

    // No other select control on the surface (owner rule: system dropdown only).
    const { container } = render(<MergeIdeasDialog ideas={ideas} onClose={vi.fn()} onMerge={vi.fn()} />);
    expect(container.querySelector('select')).toBeNull();
    expect(screen.getAllByRole('combobox')).toHaveLength(2); // one per render() call above
  });

  it('enables Merge once a survivor is picked, and calls onMerge(survivorId)', async () => {
    const user = userEvent.setup();
    const onMerge = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    const ideas = [
      anIdea({ id: 'a', ideaNumber: 'IDEA-0012', problem: 'Faster quotation' }),
      anIdea({ id: 'b', ideaNumber: 'IDEA-0013', problem: 'Faster quote generator' }),
    ];
    render(<MergeIdeasDialog ideas={ideas} onClose={onClose} onMerge={onMerge} />);

    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByText(/IDEA-0012.*Faster quotation/i));

    const mergeButton = screen.getByRole('button', { name: /^merge$/i });
    expect(mergeButton).toBeEnabled();
    await user.click(mergeButton);
    expect(onMerge).toHaveBeenCalledWith('a');
  });
});
