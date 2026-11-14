import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PortalActivity, PortalColumn, PortalIdea } from '@/types/idea-portal';

/** Lane IDEA-PORTAL component tests (AC-P-50/52/53/54/60/61). Hooks mocked at
 * the hook boundary, like the public idea page tests. */

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/portal/ideas',
  useParams: () => ({}),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v.slice(0, 10),
    formatDateTime: (v: string) => `DT:${v.slice(0, 10)}`,
    formatTime: (v: string) => v.slice(11, 16),
  }),
}));
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({
    branding: { isBranded: true, tenantName: 'Sorento', appName: null, slogan: null, logoUrl: null, faviconUrl: null, illustrationUrl: null, tokens: null, version: 0 },
    isResolved: true,
  }),
}));

const pageHook = vi.hoisted(() => vi.fn());
const principal = vi.hoisted(() => ({ current: { kind: 'crm', name: 'Aiman', role: 'Staff', productId: null, canManage: false } }));
vi.mock('@/hooks/use-idea-portal', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-idea-portal')>('@/hooks/use-idea-portal');
  return {
    ...actual,
    useIdeaPortal: () => ({
      mode: 'portal',
      paths: actual.PORTAL_PATHS,
      principal: principal.current,
      signOut: vi.fn(),
    }),
    usePortalIdeaPage: (id: string) => pageHook(id),
  };
});

import { IdeaPage } from './idea-page';
import { RoadmapBoard } from './roadmap-board';

function q<T>(data: T | null) {
  return { data, loading: false, error: null, notFound: false, reload: vi.fn(), setData: vi.fn() };
}

const idea: PortalIdea = {
  id: 'i10',
  ideaNumber: 'IDEA-0010',
  title: 'Order status tracking for dealers',
  upvotes: 2,
  commentCount: 1,
  isMine: true,
  myVote: false,
  column: 'under_review',
  statusLabel: 'New',
  statusColor: 'blue',
  productName: 'Sorento CRM',
  submittedAt: '2026-10-02T06:31:00Z',
  problem: 'Dealers cannot track the status after they place an order.',
  desiredOutcome: null,
  useCases: ['Customer asks when the basin arrives', 'Plan showroom install'],
  currentWorkaround: 'Call the sales team.',
  submitterFirstName: 'Aiman',
  timeline: [
    { key: 'under_review', label: 'Under review', color: 'blue', state: 'current' },
    { key: 'planned', label: 'Planned', color: 'violet', state: 'upcoming' },
  ],
  portalHidden: null,
  note: null,
};

const staffComment = {
  id: 'c1', ideaId: 'i10', parentId: null, authorName: 'Nadia', authorKind: 'user', authorRole: 'Staff',
  body: 'We will look at it.', isDeleted: false, isMine: false, canEdit: false, canDelete: false,
  createdAt: '2026-10-10T08:40:00Z', editedAt: null, likeCount: 1, likedByMe: false,
};
const reply = { ...staffComment, id: 'c2', parentId: 'c1', authorName: 'Aiman', authorKind: 'embed', authorRole: 'Staff', body: 'Thanks', isMine: true, canDelete: true, likeCount: 0 };
const base = { by: null, source: null, fromLabel: null, toLabel: null, toColor: null, comment: null, replies: [], commentId: null };
const activity: PortalActivity[] = [
  { ...base, kind: 'status_changed', at: '2026-10-11T02:02:00Z', fromLabel: 'New', toLabel: 'Triaged', toColor: 'indigo' },
  { ...base, kind: 'comment', at: '2026-10-10T08:40:00Z', comment: staffComment, replies: [reply] },
  { ...base, kind: 'upvote', at: '2026-10-09T03:00:00Z', by: 'Hafiz' },
  { ...base, kind: 'upvote', at: '2026-10-09T02:00:00Z', by: null },
  { ...base, kind: 'upvote', at: '2026-10-09T01:00:00Z', by: null },
  { ...base, kind: 'submitted', at: '2026-10-02T06:31:00Z', by: 'Aiman', source: 'whatsapp' },
];

function mockPage(over: Partial<ReturnType<typeof basePage>> = {}) {
  const p = { ...basePage(), ...over };
  pageHook.mockReturnValue(p);
  return p;
}
function basePage() {
  return {
    idea: q<PortalIdea>(idea),
    voters: q([{ name: 'Hafiz', role: 'Staff', isMe: false }, { name: null, role: 'Staff', isMe: false }]),
    activity: q(activity),
    order: 'desc' as const,
    setOrder: vi.fn(),
    vote: vi.fn().mockResolvedValue(undefined),
    addComment: vi.fn().mockResolvedValue(undefined),
    deleteComment: vi.fn().mockResolvedValue(undefined),
    likeComment: vi.fn().mockResolvedValue(undefined),
    setHidden: vi.fn().mockResolvedValue(undefined),
    setNote: vi.fn().mockResolvedValue(undefined),
    actionError: null as string | null,
  };
}

describe('IdeaPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows exactly the owner-ruled fields, skipping empty ones', () => {
    mockPage();
    render(<IdeaPage ideaId="i10" />);
    const fields = screen.getByTestId('portal-idea-fields');
    expect(within(fields).getByText('Business problem')).toBeInTheDocument();
    expect(within(fields).getByText('Use cases')).toBeInTheDocument();
    expect(within(fields).getByText('Current workaround')).toBeInTheDocument();
    expect(within(fields).queryByText('Desired outcome')).toBeNull();
    // Use cases render one bullet per entry.
    expect(within(fields).getByText('Plan showroom install').tagName).toBe('LI');
    for (const dropped of ['Proposed solution', 'Impact', 'Department']) {
      expect(screen.queryByText(dropped)).toBeNull();
    }
  });

  it('hero: number, title, status, Your idea, upvote box toggles', async () => {
    const p = mockPage();
    render(<IdeaPage ideaId="i10" />);
    const hero = screen.getByTestId('portal-idea-hero');
    expect(within(hero).getByText('IDEA-0010')).toBeInTheDocument();
    expect(within(hero).getByRole('heading', { level: 1 })).toHaveTextContent('Order status tracking for dealers');
    expect(within(hero).getByText('New')).toBeInTheDocument();
    expect(within(hero).getByText('Your idea')).toBeInTheDocument();
    await userEvent.click(within(hero).getByRole('button', { name: /upvote \(2\)/i }));
    expect(p.vote).toHaveBeenCalledTimes(1);
  });

  it('activity feed: status change, threaded reply, grouped upvotes, submitted', () => {
    mockPage();
    render(<IdeaPage ideaId="i10" />);
    const feed = screen.getByTestId('portal-activity');
    const kinds = Array.from(feed.children).map((li) => li.getAttribute('data-kind'));
    expect(kinds).toEqual(['status_changed', 'comment', 'upvotes', 'submitted']);
    expect(within(feed).getByText('Triaged')).toBeInTheDocument();
    expect(within(feed).getByText('Thanks')).toBeInTheDocument();
    expect(within(feed).getByText(/and 2 others upvoted/)).toBeInTheDocument();
    expect(within(feed).getByText(/over WhatsApp/)).toBeInTheDocument();
  });

  it('comment: post, like, reply, delete own only', async () => {
    const p = mockPage();
    render(<IdeaPage ideaId="i10" />);
    await userEvent.type(screen.getByLabelText('Leave a comment'), '  Branch stock next please ');
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect(p.addComment).toHaveBeenCalledWith('Branch stock next please');

    const comments = screen.getAllByTestId('portal-comment');
    await userEvent.click(within(comments[0]).getByRole('button', { name: 'Like' }));
    expect(p.likeComment).toHaveBeenCalledWith('c1');
    // Staff's comment is not deletable by a dealer; the dealer's own reply is.
    expect(within(comments[0]).queryByRole('button', { name: 'Delete comment' })).toBeNull();
    await userEvent.click(within(comments[1]).getByRole('button', { name: 'Delete comment' }));
    expect(p.deleteComment).toHaveBeenCalledWith('c2');

    await userEvent.click(within(comments[0]).getByRole('button', { name: /reply/i }));
    await userEvent.type(screen.getByLabelText('Write a reply'), 'ok');
    await userEvent.click(screen.getByRole('button', { name: 'Send reply' }));
    expect(p.addComment).toHaveBeenLastCalledWith('ok', 'c1');
  });

  it('voters show name or role, never blank; no manager controls for a non-manager', () => {
    mockPage({ idea: q<PortalIdea>({ ...idea, column: 'complete' }) });
    render(<IdeaPage ideaId="i10" />);
    const voters = screen.getByTestId('portal-voters');
    expect(within(voters).getByText('Hafiz')).toBeInTheDocument();
    expect(within(voters).getAllByText('Staff').length).toBe(3);
    expect(screen.queryByLabelText('Hide from portal')).toBeNull();
    expect(screen.queryByTestId('portal-note-editor')).toBeNull();
  });

  it('a manager gets the hide switch and, on a complete idea, the changelog note', async () => {
    principal.current = { ...principal.current, canManage: true };
    const p = mockPage({ idea: q<PortalIdea>({ ...idea, column: 'complete', portalHidden: false, note: null }) });
    render(<IdeaPage ideaId="i10" />);
    await userEvent.click(screen.getByLabelText('Hide from portal'));
    expect(p.setHidden).toHaveBeenCalledWith(true);
    const save = screen.getByRole('button', { name: 'Save note' });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Changelog note'), ' Order steps are live ');
    await userEvent.click(save);
    expect(p.setNote).toHaveBeenCalledWith('Order steps are live');
    principal.current = { ...principal.current, canManage: false };
  });

  it('not found → the uniform message', () => {
    mockPage({ idea: { ...q<PortalIdea>(idea), data: null, notFound: true } });
    render(<IdeaPage ideaId="nope" />);
    expect(screen.getByText('This idea isn’t available.')).toBeInTheDocument();
  });
});

describe('RoadmapBoard', () => {
  it('renders columns in order with counts and links to the idea page', async () => {
    const card = { ...idea, id: 'a', title: 'Quotation knowledge capture', isMine: false, myVote: true, upvotes: 4 };
    const columns: PortalColumn[] = [
      { key: 'under_review', title: 'Under review', color: 'blue', count: 7, ideas: [card] },
      { key: 'planned', title: 'Planned', color: 'violet', count: 0, ideas: [] },
    ];
    const onVote = vi.fn();
    render(<RoadmapBoard columns={columns} ideaHref={(id) => `/portal/ideas/${id}`} onVote={onVote} />);
    const sections = screen.getAllByRole('region');
    expect(sections.map((s) => s.getAttribute('aria-label'))).toEqual(['Under review', 'Planned']);
    expect(within(sections[1]).getByText('No ideas')).toBeInTheDocument();
    expect(within(sections[0]).getByText('7')).toBeInTheDocument(); // the column total, not the capped card count
    const link = within(sections[0]).getByTestId('portal-idea-card');
    expect(link).toHaveAttribute('href', '/portal/ideas/a');
    const box = within(link).getByRole('button', { name: /remove upvote \(4\)/i });
    expect(box).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(box);
    expect(onVote).toHaveBeenCalledWith('a');
  });
});

describe('groupFeed', () => {
  it('folds same-local-day upvotes; a UTC+8 viewer splits a UTC day boundary correctly', async () => {
    const { groupFeed } = await import('./idea-page');
    const up = (at: string, by: string | null) => ({ ...base, kind: 'upvote' as const, at, by });
    // 15:30Z and 17:30Z are the same UTC day but different KL days.
    const events = [up('2026-10-09T17:30:00Z', 'Hafiz'), up('2026-10-09T15:30:00Z', 'Ravi'), up('2026-10-09T15:00:00Z', null)];
    const utc = groupFeed(events, 'UTC');
    expect(utc).toHaveLength(1);
    expect(utc[0]).toMatchObject({ kind: 'upvotes', count: 3, names: ['Hafiz', 'Ravi'] });
    const kl = groupFeed(events, 'Asia/Kuala_Lumpur');
    expect(kl.map((r) => (r.kind === 'upvotes' ? r.count : 0))).toEqual([1, 2]);
  });
});
