import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Idea } from '@/types/ideation';
import type { UseIdeas } from '@/hooks/use-ideas';
import BoardPage from './page';

const useIdeas = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-ideas', () => ({ useIdeas: () => useIdeas() }));

// SettingsProvider-free: Container reads layout tokens; PageHeader calls
// useTerminology()/useSession() (network + NextAuth context this test has
// none of) - stub both so the board's data states render in isolation.
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/platform/page-header', () => ({
  PageHeader: ({ description }: { description?: React.ReactNode }) => (
    <div>
      <h1>Board</h1>
      {description}
    </div>
  ),
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
  upvotes: 3,
  downvotes: 1,
  myVote: null,
  priority: 1,
  attachments: [],
  createdAt: '2026-07-18T00:00:00Z',
  isTest: false,
  ...over,
});

const base: UseIdeas = {
  ideas: [],
  products: [],
  loading: false,
  error: null,
  includeTest: false,
  setIncludeTest: vi.fn(),
  reload: vi.fn(),
  create: vi.fn(),
  setStatus: vi.fn(),
  vote: vi.fn(),
  reorderPriority: vi.fn(),
  remove: vi.fn(),
};

beforeEach(() => useIdeas.mockReset());

describe('IdeationBoardPage', () => {
  it('shows the loading state before ideas arrive', () => {
    useIdeas.mockReturnValue({ ...base, loading: true });
    render(<BoardPage />);
    expect(screen.getByText(/loading board/i)).toBeInTheDocument();
  });

  it('shows the error state when the load failed', () => {
    useIdeas.mockReturnValue({ ...base, error: 'Could not load ideas.' });
    render(<BoardPage />);
    expect(screen.getByText('Could not load ideas.')).toBeInTheDocument();
  });

  it('renders all five columns with drop prompts when empty', () => {
    useIdeas.mockReturnValue({ ...base });
    render(<BoardPage />);
    for (const title of ['New', 'Triaged', 'Linked to BR', 'Building', 'Delivered']) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.getAllByText(/drop ideas here/i)).toHaveLength(5);
  });

  it('renders an idea card in its lifecycle column (data state)', () => {
    useIdeas.mockReturnValue({ ...base, ideas: [anIdea(), anIdea({ id: 'idea-2', status: 'triaged', problem: 'Bulk approve' })] });
    render(<BoardPage />);
    expect(screen.getByText('Export orders to Excel')).toBeInTheDocument();
    expect(screen.getByText('Bulk approve')).toBeInTheDocument();
  });

  // AC-1106 (ideation intake redesign, S1) - the card's visible label is the
  // idea's title when set, falling back to the problem text otherwise.
  it('shows the idea title as the visible label when set, not the problem text', () => {
    useIdeas.mockReturnValue({
      ...base,
      ideas: [
        anIdea({
          // @ts-expect-error - title lands on Idea in the S1 slice (not yet typed).
          title: 'Show promo price in red on price tags',
          problem: 'the price tag should show promo price in red',
        }),
      ],
    });
    render(<BoardPage />);
    expect(screen.getByText('Show promo price in red on price tags')).toBeInTheDocument();
    expect(
      screen.queryByText('the price tag should show promo price in red'),
    ).not.toBeInTheDocument();
  });

  it('falls back to the problem text when the idea has no title (pre-lane idea)', () => {
    useIdeas.mockReturnValue({
      ...base,
      // @ts-expect-error - title lands on Idea in the S1 slice (not yet typed).
      ideas: [anIdea({ title: null, problem: 'Legacy idea created before this lane' })],
    });
    render(<BoardPage />);
    expect(screen.getByText('Legacy idea created before this lane')).toBeInTheDocument();
  });

  // AC-1115 - the board card shows the submitter's tier when set.
  it('renders the submitter tier on the card when set', () => {
    useIdeas.mockReturnValue({
      ...base,
      // @ts-expect-error - submitterTier lands on Idea in the S1 slice (not yet typed).
      ideas: [anIdea({ submitterTier: 'dealer' })],
    });
    render(<BoardPage />);
    expect(screen.getByText(/dealer/i)).toBeInTheDocument();
  });
});
