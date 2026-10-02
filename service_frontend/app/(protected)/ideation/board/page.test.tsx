import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BoardColumn, Idea } from '@/types/ideation';
import type { UseIdeas } from '@/hooks/use-ideas';
import { canMoveTo } from './triage-board';
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
  statusId: 'idea-status-captured',
  statusLabel: 'New',
  statusColor: 'blue',
  statusIsArchived: false,
  transitions: [
    { id: 'idea-tr-1', label: 'Triage', toStatusId: 'idea-status-triaged', toStatusLabel: 'Triaged' },
  ],
  advanceTransitionId: 'idea-tr-1',
  rank: 1,
  mergedIntoId: null,
  mergedInto: null,
  mergedCount: 0,
  ...over,
});

// AC-94-54/58 (issue #94, ideation round 2) - columns come from the API
// (`GET /board`), never a hardcoded frontend column list.
const COLUMNS: BoardColumn[] = [
  { statusId: 'idea-status-captured', key: 'captured', title: 'New', color: 'blue', ideas: [] },
  { statusId: 'idea-status-triaged', key: 'triaged', title: 'Triaged', color: 'amber', ideas: [] },
  { statusId: 'idea-status-linked', key: 'linked', title: 'Linked to BR', color: 'violet', ideas: [] },
  { statusId: 'idea-status-building', key: 'building', title: 'Building', color: 'indigo', ideas: [] },
  { statusId: 'idea-status-delivered', key: 'delivered', title: 'Delivered', color: 'emerald', ideas: [] },
];

const base: UseIdeas = {
  ideas: [],
  products: [],
  loading: false,
  error: null,
  columns: COLUMNS,
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
    useIdeas.mockReturnValue({
      ...base,
      ideas: [
        anIdea(),
        anIdea({ id: 'idea-2', status: 'triaged', statusId: 'idea-status-triaged', problem: 'Bulk approve' }),
      ],
    });
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
      ideas: [anIdea({ title: null, problem: 'Legacy idea created before this lane' })],
    });
    render(<BoardPage />);
    expect(screen.getByText('Legacy idea created before this lane')).toBeInTheDocument();
  });

  // AC-1115 - the board card shows the submitter's tier when set.
  it('renders the submitter tier on the card when set', () => {
    useIdeas.mockReturnValue({
      ...base,
      ideas: [anIdea({ submitterTier: 'dealer' })],
    });
    render(<BoardPage />);
    expect(screen.getByText(/dealer/i)).toBeInTheDocument();
  });

  // ── AC-19-17 (plan 19) - the card uses the same sm vote box; score = upvotes ──
  it('the card renders the sm upvote box with the upvote count only (no down count, no net score)', () => {
    useIdeas.mockReturnValue({ ...base, ideas: [anIdea({ upvotes: 3, downvotes: 1 })] });
    render(<BoardPage />);
    const up = screen.getByRole('button', { name: /upvote/i });
    expect(up).toHaveTextContent('3');
    const box = up.closest('[data-variant="box"]');
    expect(box).not.toBeNull();
    expect(box?.getAttribute('data-size')).toBe('sm');
    expect(screen.queryByRole('button', { name: /downvote/i })).not.toBeInTheDocument();
    expect(screen.queryByText('2')).not.toBeInTheDocument(); // the old net score 3 - 1
    expect(screen.queryByText('1')).not.toBeInTheDocument(); // the old downvote count
  });

  // ── AC-94-58 (issue #94, ideation round 2) ──────────────────────────────────

  it('columns from API - a tenant rename shows up with zero code change (never a hardcoded frontend column list)', () => {
    const renamed: BoardColumn[] = [
      { statusId: 'idea-status-captured', key: 'captured', title: 'New', color: 'blue', ideas: [] },
      { statusId: 'idea-status-triaged', key: 'triaged', title: 'Discussed', color: 'amber', ideas: [] },
    ];
    useIdeas.mockReturnValue({ ...base, columns: renamed, ideas: [] });
    render(<BoardPage />);
    expect(screen.getByText('Discussed')).toBeInTheDocument();
    expect(screen.queryByText('Triaged')).not.toBeInTheDocument();
  });

  it('invalid drop refused - a card can only move to a column its OWN transitions reach', () => {
    const idea = anIdea({
      transitions: [
        { id: 'idea-tr-1', label: 'Triage', toStatusId: 'idea-status-triaged', toStatusLabel: 'Triaged' },
      ],
    });
    // The card's transitions reach "triaged" - not "building" (skipping
    // stages is never offered, foolproof-UI).
    expect(canMoveTo(idea, 'idea-status-triaged')).toBe(true);
    expect(canMoveTo(idea, 'idea-status-building')).toBe(false);
    expect(canMoveTo(undefined, 'idea-status-triaged')).toBe(false);
  });
});
