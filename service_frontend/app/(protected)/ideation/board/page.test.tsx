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
  ...over,
});

const base: UseIdeas = {
  ideas: [],
  products: [],
  loading: false,
  error: null,
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
});
