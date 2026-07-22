import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Idea, IdeaClusterSuggestions } from '@/types/ideation';
import { IdeaClusterSuggestions as ClusterSuggestions } from './cluster-suggestions';

const canMock = vi.fn((): boolean => true);
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: canMock, ready: true }),
}));

const suggestClusters = vi.fn();
vi.mock('@/services/ideation-service', () => ({
  ideationService: {
    suggestClusters: (...args: unknown[]) => suggestClusters(...args),
  },
}));

const idea = (id: string, problem: string): Idea => ({
  id,
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'captured',
  problem,
  proposedSolution: null,
  impact: null,
  department: null,
  rawText: problem,
  source: 'manual',
  submitterName: 'Aisha',
  upvotes: 0,
  downvotes: 0,
  myVote: null,
  priority: 0,
  attachments: [],
  createdAt: '2026-07-20T10:00:00Z',
});

const SUGGESTIONS: IdeaClusterSuggestions = {
  degraded: false,
  clusters: [
    {
      label: 'Slow checkout',
      productId: 'prod-1',
      ideaIds: ['i1', 'i2'],
      ideas: [idea('i1', 'Checkout is slow'), idea('i2', 'Payment page takes forever')],
    },
  ],
};

describe('IdeaClusterSuggestions', () => {
  beforeEach(() => {
    canMock.mockReturnValue(true);
    suggestClusters.mockReset();
  });

  it('is hidden without the clusters.manage permission', () => {
    canMock.mockReturnValue(false);
    const { container } = render(<ClusterSuggestions onPromote={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('fetches + renders suggested clusters on demand', async () => {
    suggestClusters.mockResolvedValue(SUGGESTIONS);
    render(<ClusterSuggestions onPromote={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /suggest clusters/i }));
    expect(await screen.findByText('Slow checkout')).toBeInTheDocument();
    expect(screen.getByText('Checkout is slow')).toBeInTheDocument();
    expect(screen.getByText('Payment page takes forever')).toBeInTheDocument();
  });

  it('promotes only the (edited) selected ideas of a cluster', async () => {
    suggestClusters.mockResolvedValue(SUGGESTIONS);
    const onPromote = vi.fn().mockResolvedValue(undefined);
    render(<ClusterSuggestions onPromote={onPromote} />);
    fireEvent.click(screen.getByRole('button', { name: /suggest clusters/i }));
    await screen.findByText('Slow checkout');

    // Both ideas selected by default → deselect the second.
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes).toHaveLength(2);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole('button', { name: /promote 1 to br/i }));
    await waitFor(() => expect(onPromote).toHaveBeenCalledTimes(1));
    const promoted = onPromote.mock.calls[0][0] as Idea[];
    expect(promoted.map((i) => i.id)).toEqual(['i1']);
  });
});
