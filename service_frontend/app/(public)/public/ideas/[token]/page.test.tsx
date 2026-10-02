import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IdeaComment } from '@/types/ideation';
import PublicIdeaStatusPage from './page';

/**
 * S5 public idea status page (AC-1601, AC-1106, AC-1115), grown into a full
 * page by issue #90 (AC-90-110/111/112). TEST-FIRST (PRINCIPLES.md). Mocks
 * next/navigation's useParams, the data hook, and the branding hook (the
 * header/footer BrandMark) so this exercises only the page's render logic,
 * per the sibling `public-form-service`/`use-public-share` test style.
 */

const useParams = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useParams: () => useParams() }));

const usePublicIdeaStatus = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-public-idea-status', () => ({
  usePublicIdeaStatus: (token: string) => usePublicIdeaStatus(token),
}));

// Plan 19 section F: the thread is read through the public comments hook
// (mocked at the hook boundary, like the status hook above).
const usePublicIdeaComments = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-public-idea-comments', () => ({
  usePublicIdeaComments: (token: string) => usePublicIdeaComments(token),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v.slice(0, 10),
    formatDateTime: (v: string) => `DT:${v.slice(0, 10)}`,
    formatTime: (v: string) => v.slice(11, 16),
  }),
}));

const useTenantBranding = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => useTenantBranding(),
}));

const UNBRANDED = {
  isBranded: false,
  tenantName: null,
  appName: null,
  slogan: null,
  logoUrl: null,
  faviconUrl: null,
  illustrationUrl: null,
  tokens: null,
  version: 0,
};

const richView = {
  ideaNumber: 'IDEA-0182',
  title: 'Show promo price in red on price tags',
  status: 'New',
  statusColor: 'blue',
  productName: 'Sorento CRM',
  problem: 'Promo price is not visible in-store',
  proposedSolution: 'Print it in red on the price tag',
  impact: 'Fewer missed promotions at checkout',
  department: 'Merchandising',
  submitterFirstName: 'Jayson',
  submittedAt: '2026-07-20T10:00:00Z',
  upvotes: 7,
  nextStep: 'Your idea is in. The team will review it soon.',
  timeline: [
    { label: 'New', color: 'blue', state: 'done' },
    { label: 'Triaged', color: 'indigo', state: 'current' },
    { label: 'Linked to BR', color: 'violet', state: 'upcoming' },
    { label: 'Building', color: 'amber', state: 'upcoming' },
    { label: 'Delivered', color: 'green', state: 'upcoming' },
  ],
};

const emptyComments = () => ({
  threads: [],
  count: 0,
  loading: false,
  error: null,
  add: vi.fn().mockResolvedValue(undefined),
});

beforeEach(() => {
  usePublicIdeaComments.mockReset();
  usePublicIdeaComments.mockReturnValue(emptyComments());
  useParams.mockReset();
  usePublicIdeaStatus.mockReset();
  useTenantBranding.mockReset();
  useParams.mockReturnValue({ token: 'tok_abc123def456' });
  useTenantBranding.mockReturnValue({ branding: UNBRANDED, isResolved: true });
});

describe('PublicIdeaStatusPage - AC-90-110 the full page contract', () => {
  it('renders the header product name, hero, votes, sections, next step and footer mark', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);

    // Header - product name (R1: the idea's core Product).
    expect(screen.getByText('Sorento CRM')).toBeInTheDocument();

    // Hero.
    const hero = screen.getByTestId('idea-hero');
    expect(within(hero).getByText('IDEA-0182')).toBeInTheDocument();
    expect(
      within(hero).getByText('Show promo price in red on price tags'),
    ).toBeInTheDocument();
    // The status pill (SAME StatusBadge pill the Ideas app uses) shows the
    // CURRENT status - scoped to the hero because a timeline step can carry
    // the exact same label (the current one always does; an off-ramp's
    // `done` step sometimes coincidentally does too, see AC-90-111 below) -
    // a bare-text query for the status word is ambiguous unless scoped to
    // ONE region, never a reason to drop the pill itself.
    expect(within(hero).getByText('New')).toBeInTheDocument();
    expect(within(hero).getByText(/Jayson/)).toBeInTheDocument();
    expect(within(hero).getByText(/2026/)).toBeInTheDocument(); // submittedAt rendered
    expect(within(hero).getByText(/7/)).toBeInTheDocument(); // upvotes

    // Detail sections - labelled per idea-form-fields.tsx (Problem statement /
    // Proposed solution / Impact / Department).
    expect(screen.getByText('Problem statement')).toBeInTheDocument();
    expect(screen.getByText('Promo price is not visible in-store')).toBeInTheDocument();
    expect(screen.getByText('Proposed solution')).toBeInTheDocument();
    expect(screen.getByText('Print it in red on the price tag')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
    expect(screen.getByText('Fewer missed promotions at checkout')).toBeInTheDocument();
    expect(screen.getByText('Department')).toBeInTheDocument();
    expect(screen.getByText('Merchandising')).toBeInTheDocument();

    // "What happens next".
    expect(
      screen.getByText('Your idea is in. The team will review it soon.'),
    ).toBeInTheDocument();

    // Footer mark - unbranded host shows the Foundryx wordmark (inline SVG,
    // review fix B1 - never an <img> pointed at a file that isn't committed).
    expect(screen.getByRole('img', { name: 'Foundryx' })).toBeInTheDocument();
  });

  // Supersedes (REWRITTEN, not deleted) the old AC-1601
  // "never renders any problem/solution/impact/department text" test - issue
  // #90 makes these fields part of the page; the empty-state contract now is
  // "always render the section, 'Not provided' when blank", never omission.
  it('renders "Not provided" for empty detail sections and omits the submitter line when there is no first name', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ...richView,
        problem: null,
        proposedSolution: null,
        impact: null,
        department: null,
        submitterFirstName: null,
      },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getAllByText('Not provided').length).toBe(4);
    expect(screen.queryByText('Jayson')).not.toBeInTheDocument();
  });

  it('shows the tenant name (not the Foundryx mark) on a branded host', () => {
    useTenantBranding.mockReturnValue({
      branding: { ...UNBRANDED, isBranded: true, tenantName: 'Acme Co', logoUrl: null },
      isResolved: true,
    });
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);
    expect(screen.queryByRole('img', { name: 'Foundryx' })).not.toBeInTheDocument();
    expect(screen.getAllByText('Acme Co').length).toBeGreaterThan(0);
  });
});

describe('PublicIdeaStatusPage - AC-90-111 the status timeline', () => {
  it('renders one entry per timeline step with its state, done/current/upcoming', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);
    // Scoped to the timeline region - the CURRENT step's label also renders
    // as the hero's status pill (by design, AC-90-110), so a page-wide query
    // for that label would be ambiguous.
    const timeline = screen.getByTestId('idea-status-timeline');
    for (const step of richView.timeline) {
      const el = within(timeline).getByText(step.label);
      const item = el.closest('[data-state]');
      expect(item).not.toBeNull();
      expect(item).toHaveAttribute('data-state', step.state);
    }
  });

  it('renders the truthful short off-ramp timeline (New done, Rejected current)', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: {
        ...richView,
        status: 'Rejected',
        nextStep: 'This idea will not go ahead for now.',
        timeline: [
          { label: 'New', color: 'blue', state: 'done' },
          { label: 'Rejected', color: 'red', state: 'current' },
        ],
      },
    });
    render(<PublicIdeaStatusPage />);
    // Scoped to the timeline - the hero's pill ALSO shows "Rejected" (the
    // current status), which would otherwise ambiguously match too.
    const timeline = screen.getByTestId('idea-status-timeline');
    const newItem = within(timeline).getByText('New').closest('[data-state]');
    const rejectedItem = within(timeline).getByText('Rejected').closest('[data-state]');
    expect(newItem).toHaveAttribute('data-state', 'done');
    expect(rejectedItem).toHaveAttribute('data-state', 'current');
    // The status pill shows the CURRENT status too (AC-90-110's pill
    // assertion, repeated here since this fixture's status differs from the
    // main-path one above).
    const hero = screen.getByTestId('idea-hero');
    expect(within(hero).getByText('Rejected')).toBeInTheDocument();
  });
});

describe('PublicIdeaStatusPage - merged child (issue #94, AC-94-13/31)', () => {
  it('shows "Merged into IDEA-xxxx" while the survivor drives status/timeline', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ...richView, mergedInto: { ideaNumber: 'IDEA-0012', title: 'Faster quotation' } },
    });
    render(<PublicIdeaStatusPage />);
    const hero = screen.getByTestId('idea-hero');
    expect(within(hero).getByText('Merged into IDEA-0012')).toBeInTheDocument();
  });

  it('renders nothing extra for a plain (never-merged) idea', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
    render(<PublicIdeaStatusPage />);
    expect(screen.queryByText(/Merged into/)).not.toBeInTheDocument();
  });
});

describe('PublicIdeaStatusPage - not-found (regression, unchanged)', () => {
  it('renders the not-found state when the hook reports not found', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: true, view: null });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByTestId('idea-status-notfound')).toBeInTheDocument();
  });

  // Review fix S5: a null title used to fall back to "Idea <number>", which
  // repeated the number the muted line above it already shows - REWRITTEN
  // (not deleted): a null title now falls back to the (truncated) problem
  // text, never a second echo of the number.
  it('falls back to the problem text as the heading when title is null but problem is present', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ...richView, title: null },
    });
    render(<PublicIdeaStatusPage />);
    const hero = screen.getByTestId('idea-hero');
    expect(within(hero).getByText(richView.problem)).toBeInTheDocument();
    expect(screen.queryByText('Idea IDEA-0182')).not.toBeInTheDocument();
    // The number itself still renders exactly once (the muted line).
    expect(screen.getAllByText('IDEA-0182').length).toBe(1);
  });

  it('shows the idea number exactly once when both title and problem are null', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ...richView, title: null, problem: null },
    });
    render(<PublicIdeaStatusPage />);
    expect(screen.getAllByText('IDEA-0182').length).toBe(1);
    expect(screen.queryByText('Idea IDEA-0182')).not.toBeInTheDocument();
  });
});


// ── Plan 19 section F (AC-19-33/34) - public comments ───────────────────────────

const pc = (over: Partial<IdeaComment>): IdeaComment => ({
  id: 'c1',
  ideaId: 'idea-1',
  parentId: null,
  authorName: 'Jayson',
  authorKind: 'public',
  body: 'Thanks for looking at this',
  isDeleted: false,
  isMine: false,
  canEdit: false,
  canDelete: false,
  createdAt: '2026-10-01T08:00:00Z',
  editedAt: null,
  ...over,
});

function withComments(
  threads: { root: IdeaComment; replies: IdeaComment[] }[],
  over: Record<string, unknown> = {},
) {
  const value = { ...emptyComments(), threads, count: threads.reduce((n, t) => n + 1 + t.replies.length, 0), ...over };
  usePublicIdeaComments.mockReturnValue(value);
  return value as ReturnType<typeof emptyComments>;
}

describe('PublicIdeaStatusPage - comments thread (AC-19-33)', () => {
  beforeEach(() => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
  });

  it('reads the thread by the URL token', () => {
    render(<PublicIdeaStatusPage />);
    expect(usePublicIdeaComments).toHaveBeenCalledWith('tok_abc123def456');
  });

  it('shows "Comments <n>" with the thread oldest first, replies indented, plain text', () => {
    withComments([
      {
        root: pc({ id: 'c1' }),
        replies: [pc({ id: 'r1', parentId: 'c1', authorKind: 'user', authorName: 'Staff Sam', body: '<b>on it</b>' })],
      },
      { root: pc({ id: 'c2', body: 'second thread', createdAt: '2026-10-02T08:00:00Z' }), replies: [] },
    ]);
    const { container } = render(<PublicIdeaStatusPage />);
    expect(screen.getByRole('heading', { name: /^Comments/ })).toBeInTheDocument();
    expect(screen.getByTestId('comments-count')).toHaveTextContent('3');
    const threads = screen.getAllByTestId('comment-thread');
    expect(threads).toHaveLength(2);
    expect(within(threads[0]).getByText('Thanks for looking at this')).toBeInTheDocument();
    const reply = within(threads[0]).getByTestId('comment-reply');
    expect(within(reply).getByText('Staff Sam')).toBeInTheDocument();
    expect(within(reply).getByText('<b>on it</b>')).toBeInTheDocument();
    expect(container.querySelector('b')).toBeNull();
  });

  it('public comments show a "Submitter" badge after the name; staff ones do not (AC-19-34)', () => {
    withComments([
      { root: pc({ id: 'c1' }), replies: [pc({ id: 'r1', parentId: 'c1', authorKind: 'user', authorName: 'Staff Sam', body: 'hi' })] },
    ]);
    render(<PublicIdeaStatusPage />);
    const [t] = screen.getAllByTestId('comment-thread');
    expect(within(t).getAllByText('Submitter')).toHaveLength(1);
  });

  it('a deleted comment with replies shows "Comment deleted"', () => {
    withComments([
      {
        root: pc({ id: 'c1', isDeleted: true, body: null, authorName: null }),
        replies: [pc({ id: 'r1', parentId: 'c1', body: 'reply stays' })],
      },
    ]);
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('Comment deleted')).toBeInTheDocument();
  });

  it('empty thread reads "No comments."', () => {
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('No comments.')).toBeInTheDocument();
  });

  it('loading state for the thread', () => {
    withComments([], { loading: true });
    render(<PublicIdeaStatusPage />);
    expect(screen.getByTestId('comments-loading')).toBeInTheDocument();
  });

  it('the thread never renders when the idea is not found', () => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: true, view: null });
    render(<PublicIdeaStatusPage />);
    expect(screen.queryByRole('heading', { name: /^Comments/ })).not.toBeInTheDocument();
  });
});

describe('PublicIdeaStatusPage - posting (AC-19-33)', () => {
  beforeEach(() => {
    usePublicIdeaStatus.mockReturnValue({ loading: false, notFound: false, view: richView });
  });

  it('Comment is disabled while empty, then posts the text and clears the box', async () => {
    const user = userEvent.setup();
    const v = withComments([]);
    render(<PublicIdeaStatusPage />);
    const btn = screen.getByRole('button', { name: 'Comment' });
    expect(btn).toBeDisabled();
    await user.type(screen.getByRole('textbox'), 'My follow up');
    expect(btn).toBeEnabled();
    await user.click(btn);
    expect(v.add).toHaveBeenCalledTimes(1);
    expect(String(v.add.mock.calls[0][0]).trim()).toBe('My follow up');
    expect(v.add.mock.calls[0][1] ?? null).toBeNull();
    expect(screen.getByRole('textbox')).toHaveValue('');
  });

  it('the public composer has no author-name input (the name comes from the submitter)', () => {
    withComments([]);
    render(<PublicIdeaStatusPage />);
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
  });

  it('per-thread Reply opens an inline composer and posts add(body, rootId)', async () => {
    const user = userEvent.setup();
    const v = withComments([{ root: pc({ id: 'c1' }), replies: [] }]);
    render(<PublicIdeaStatusPage />);
    const t = screen.getByTestId('comment-thread');
    await user.click(within(t).getByRole('button', { name: 'Reply' }));
    const composer = within(t).getByTestId('reply-composer');
    await user.type(within(composer).getByRole('textbox'), 'thanks');
    await user.click(within(composer).getByRole('button', { name: 'Reply' }));
    expect(v.add).toHaveBeenCalledWith('thanks', 'c1');
  });

  it('replying to a reply posts to the top-level parent', async () => {
    const user = userEvent.setup();
    const v = withComments([
      { root: pc({ id: 'c1' }), replies: [pc({ id: 'r1', parentId: 'c1', authorKind: 'user', authorName: 'Staff Sam', body: 'hi' })] },
    ]);
    render(<PublicIdeaStatusPage />);
    await user.click(within(screen.getByTestId('comment-reply')).getByRole('button', { name: 'Reply' }));
    const composer = screen.getByTestId('reply-composer');
    await user.type(within(composer).getByRole('textbox'), 'nested');
    await user.click(within(composer).getByRole('button', { name: 'Reply' }));
    expect(v.add).toHaveBeenCalledWith('nested', 'c1');
  });

  it('offers no Edit or Delete anywhere (visitors cannot edit or delete)', () => {
    withComments([{ root: pc({ id: 'c1', isMine: true, canEdit: true, canDelete: true }), replies: [] }]);
    render(<PublicIdeaStatusPage />);
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('a merged child shows the thread but hides the composer and Reply', () => {
    usePublicIdeaStatus.mockReturnValue({
      loading: false,
      notFound: false,
      view: { ...richView, mergedInto: { ideaNumber: 'IDEA-0012', title: 'Faster quotation' } },
    });
    withComments([{ root: pc({ id: 'c1' }), replies: [] }]);
    render(<PublicIdeaStatusPage />);
    expect(screen.getByText('Thanks for looking at this')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Comment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();
  });
});
