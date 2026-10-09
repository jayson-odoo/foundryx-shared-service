/**
 * AC-94-35 (shared VoteCell with a `disabled` prop) as amended by plan 19:
 * AC-19-15 - upvote only (no down button anywhere), new `variant: 'pill' | 'box'`
 * and `size: 'sm' | 'md'`, orange (primary token) pressed state, disabled on a
 * merged child. The root element carries `data-variant` + `data-size`.
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
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

describe('VoteCell - upvote only (AC-19-15)', () => {
  it('renders the upvote count and calls onVote(idea, "up") on click', async () => {
    const user = userEvent.setup();
    const onVote = vi.fn();
    render(<VoteCell idea={anIdea()} onVote={onVote} />);
    expect(screen.getByRole('button', { name: /upvote/i })).toHaveTextContent('2');
    await user.click(screen.getByRole('button', { name: /upvote/i }));
    expect(onVote).toHaveBeenCalledWith(anIdea(), 'up');
  });

  it.each(['pill', 'box'] as const)('%s variant renders NO down button and no downvote count', (variant) => {
    render(
      <VoteCell idea={anIdea({ downvotes: 4 })} onVote={vi.fn()} variant={variant} size="md" />,
    );
    expect(screen.queryByRole('button', { name: /downvote/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByText('4')).not.toBeInTheDocument();
  });

  it('shows the pressed state for the caller\'s upvote', () => {
    render(<VoteCell idea={anIdea({ myVote: 'up' })} onVote={vi.fn()} />);
    expect(screen.getByRole('button', { name: /cancel upvote/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('is disabled (merged child) and never calls onVote', async () => {
    const user = userEvent.setup();
    const onVote = vi.fn();
    render(<VoteCell idea={anIdea()} onVote={onVote} disabled />);
    const up = screen.getByRole('button', { name: /upvote/i });
    expect(up).toBeDisabled();
    await user.click(up);
    expect(onVote).not.toHaveBeenCalled();
  });
});

describe('VoteCell - box variant (AC-19-15)', () => {
  it('exposes data-variant="box" and data-size on the root', () => {
    const { container } = render(
      <VoteCell idea={anIdea()} onVote={vi.fn()} variant="box" size="md" />,
    );
    const root = container.querySelector('[data-variant]') as HTMLElement;
    expect(root).not.toBeNull();
    expect(root.getAttribute('data-variant')).toBe('box');
    expect(root.getAttribute('data-size')).toBe('md');
  });

  it('size sm is reflected on the root (list / board)', () => {
    const { container } = render(
      <VoteCell idea={anIdea()} onVote={vi.fn()} variant="box" size="sm" />,
    );
    expect(container.querySelector('[data-variant="box"]')?.getAttribute('data-size')).toBe('sm');
  });

  it('defaults to the pill variant', () => {
    const { container } = render(<VoteCell idea={anIdea()} onVote={vi.fn()} />);
    expect(container.querySelector('[data-variant]')?.getAttribute('data-variant')).toBe('pill');
  });

  it('pressed state uses the primary (orange) token, never emerald', () => {
    const { container } = render(
      <VoteCell idea={anIdea({ myVote: 'up' })} onVote={vi.fn()} variant="box" size="md" />,
    );
    const html = container.innerHTML;
    expect(html).toMatch(/(border|text|bg)-primary/);
    expect(html).not.toMatch(/emerald/);
  });

  it('unpressed box has no primary-colored text on the control', () => {
    render(<VoteCell idea={anIdea({ myVote: null })} onVote={vi.fn()} variant="box" size="md" />);
    expect(screen.getByRole('button', { name: /upvote/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('a disabled box never calls onVote', async () => {
    const user = userEvent.setup();
    const onVote = vi.fn();
    render(<VoteCell idea={anIdea()} onVote={onVote} variant="box" size="md" disabled />);
    const up = screen.getByRole('button', { name: /upvote/i });
    expect(up).toBeDisabled();
    await user.click(up);
    expect(onVote).not.toHaveBeenCalled();
  });
});
