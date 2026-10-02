/**
 * AC-94-35 (issue #94, ideation round 2) - `VoteCell` extracted to its own
 * module (`components/vote-cell.tsx`) with a `disabled` prop, so the list AND
 * the form render the exact same control (plan section 4.2).
 *
 * TEST-FIRST (PRINCIPLES.md): `./vote-cell` doesn't exist yet - `VoteCell`
 * still lives file-local inside `use-ideas-list-config.tsx`. This fails with
 * a module-not-found error until slice S1 extracts it.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import { VoteCell } from './vote-cell';

const anIdea = (over: Partial<Idea> = {}): Idea => ({
  id: 'idea-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem: 'Export orders to Excel',
  rawText: 'raw',
  source: 'whatsapp',
  submitterName: 'Jayson',
  upvotes: 2,
  downvotes: 1,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

describe('VoteCell (AC-94-35)', () => {
  it('renders the up/down counts and calls onVote(idea, dir) on click', async () => {
    const user = userEvent.setup();
    const onVote = vi.fn();
    render(<VoteCell idea={anIdea()} onVote={onVote} />);
    expect(screen.getByRole('button', { name: /upvote/i })).toHaveTextContent('2');
    expect(screen.getByRole('button', { name: /downvote/i })).toHaveTextContent('1');
    await user.click(screen.getByRole('button', { name: /upvote/i }));
    expect(onVote).toHaveBeenCalledWith(anIdea(), 'up');
  });

  it('shows the pressed state for the caller\'s current vote', () => {
    render(<VoteCell idea={anIdea({ myVote: 'up' })} onVote={vi.fn()} />);
    expect(screen.getByRole('button', { name: /cancel upvote/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('disables both buttons when disabled (a merged child, AC-94-26)', async () => {
    const user = userEvent.setup();
    const onVote = vi.fn();
    render(<VoteCell idea={anIdea()} onVote={onVote} disabled />);
    const up = screen.getByRole('button', { name: /upvote/i });
    const down = screen.getByRole('button', { name: /downvote/i });
    expect(up).toBeDisabled();
    expect(down).toBeDisabled();
    await user.click(up);
    expect(onVote).not.toHaveBeenCalled();
  });
});
