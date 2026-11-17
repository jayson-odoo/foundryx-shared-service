import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PortalIdea } from '@/types/idea-portal';

/** Lane FEEDBACK-SUBSCRIBE (AC-FS-9): Follow / Share on the item page and the
 * read-only share view whose every action goes through the phone step. The
 * page hook is mocked; the phone step runs the real hook over a mocked service. */

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/public/feedback/share/tok',
  useParams: () => ({}),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ timeZone: 'UTC', formatDmyDate: (v: string) => v.slice(0, 10) }),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast }));

const svc = vi.hoisted(() => ({
  share: { sendCode: vi.fn(), verifyCode: vi.fn(), get: vi.fn(), comments: vi.fn(), activity: vi.fn() },
  portal: { follow: vi.fn(), vote: vi.fn() },
}));
vi.mock('@/services/idea-portal-service', () => ({
  ideaShareService: svc.share,
  ideaPortalService: svc.portal,
}));
const auth = vi.hoisted(() => ({ set: vi.fn(), get: vi.fn(), owner: vi.fn() }));
vi.mock('@/lib/idea-portal-auth', () => ({ ideaPortalAuth: auth }));

const pageHook = vi.hoisted(() => vi.fn());
const runtime = vi.hoisted(() => ({
  current: {
    mode: 'link' as string,
    shareToken: undefined as string | undefined,
    principal: { kind: 'contact', name: 'Dealer', role: 'Dealer', productId: null, canManage: false },
  },
}));
vi.mock('@/hooks/use-idea-portal', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-idea-portal')>('@/hooks/use-idea-portal');
  return {
    ...actual,
    useIdeaPortal: () => ({ ...runtime.current, paths: actual.PORTAL_PATHS, signOut: vi.fn() }),
    usePortalIdeaPage: (id: string, token?: string | null) => pageHook(id, token),
  };
});

import { IdeaPage } from './idea-page';

const idea: PortalIdea = {
  id: 'i10',
  ideaNumber: 'IDEA-0042',
  title: 'Order status tracking',
  upvotes: 2,
  commentCount: 0,
  isMine: false,
  myVote: false,
  column: 'planned',
  statusLabel: 'Planned',
  statusColor: 'blue',
  productName: null,
  submittedAt: null,
  timeline: [],
  portalHidden: null,
  note: null,
  followerCount: 2,
  following: false,
};

function q<T>(data: T | null) {
  return { data, loading: false, error: null, notFound: false, reload: vi.fn(), setData: vi.fn() };
}

function mockPage(over: Partial<PortalIdea> = {}) {
  const p = {
    idea: q<PortalIdea>({ ...idea, ...over }),
    voters: q([{ name: 'Hafiz', role: 'Dealer', isMe: false }]),
    activity: q([]),
    order: 'desc' as const,
    setOrder: vi.fn(),
    vote: vi.fn().mockResolvedValue(undefined),
    addComment: vi.fn().mockResolvedValue(undefined),
    deleteComment: vi.fn().mockResolvedValue(undefined),
    likeComment: vi.fn().mockResolvedValue(undefined),
    setHidden: vi.fn().mockResolvedValue(undefined),
    setNote: vi.fn().mockResolvedValue(undefined),
    toggleFollow: vi.fn().mockResolvedValue(undefined),
    shareUrl: vi.fn().mockResolvedValue('https://x.test/public/feedback/share/abc'),
    actionError: null as string | null,
  };
  pageHook.mockReturnValue(p);
  return p;
}

function asContact() {
  runtime.current = { ...runtime.current, mode: 'link', shareToken: undefined, principal: { ...runtime.current.principal, kind: 'contact' } };
}
function asShare() {
  runtime.current = { ...runtime.current, mode: 'share', shareToken: 'tok', principal: { ...runtime.current.principal, kind: 'share' } };
}

beforeEach(() => {
  vi.clearAllMocks();
  asContact();
});

describe('Follow / Share on the item page', () => {
  it('a contact sees Follow + the follower count, and tapping toggles', async () => {
    const p = mockPage();
    render(<IdeaPage ideaId="FB-0042" />);
    expect(screen.getByTestId('portal-follower-count')).toHaveTextContent('2 followers');
    await userEvent.click(screen.getByRole('button', { name: 'Follow' }));
    expect(p.toggleFollow).toHaveBeenCalledTimes(1);
  });

  it('following reads "Following" and one follower is singular', () => {
    mockPage({ following: true, followerCount: 1 });
    render(<IdeaPage ideaId="FB-0042" />);
    expect(screen.getByRole('button', { name: 'Following' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('portal-follower-count')).toHaveTextContent('1 follower');
  });

  it('Share opens the read-only link in a popup with an inline-checkmark copy', async () => {
    const p = mockPage();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<IdeaPage ideaId="FB-0042" />);
    await userEvent.click(screen.getByRole('button', { name: 'Share' }));
    const dialog = await screen.findByRole('dialog', { name: 'Share link' });
    expect(p.shareUrl).toHaveBeenCalledTimes(1);
    expect(await within(dialog).findByLabelText('Share link')).toHaveValue('https://x.test/public/feedback/share/abc');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy link' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://x.test/public/feedback/share/abc'));
    expect(await within(dialog).findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('a refused clipboard keeps the link visible and says so', async () => {
    mockPage();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    render(<IdeaPage ideaId="FB-0042" />);
    await userEvent.click(screen.getByRole('button', { name: 'Share' }));
    const dialog = await screen.findByRole('dialog', { name: 'Share link' });
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Copy link' }));
    expect(await within(dialog).findByText(/Copy did not work/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Share link')).toHaveValue('https://x.test/public/feedback/share/abc');
  });

  it('a staff / CRM viewer has Share but no Follow', () => {
    runtime.current = { ...runtime.current, principal: { ...runtime.current.principal, kind: 'crm' } };
    mockPage();
    render(<IdeaPage ideaId="FB-0042" />);
    expect(screen.queryByRole('button', { name: 'Follow' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Share' })).toBeInTheDocument();
  });
});

describe('the read-only share view', () => {
  beforeEach(() => asShare());

  it('reads through the share token, no back link, no voters, no Share', () => {
    mockPage();
    render(<IdeaPage ideaId="tok" />);
    expect(pageHook).toHaveBeenCalledWith('tok', 'tok');
    expect(screen.queryByText('Feedback')).toBeNull();
    expect(screen.queryByText('Roadmap')).toBeNull();
    expect(screen.queryByTestId('portal-voters')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Share' })).toBeNull();
    expect(screen.queryByRole('textbox', { name: 'Leave a comment' })).toBeNull();
  });

  it.each([
    ['Follow', 'Follow this request'],
    ['Leave a comment', 'Comment on this request'],
  ])('tapping %s asks for the phone, never acts directly', async (button, title) => {
    const p = mockPage();
    render(<IdeaPage ideaId="tok" />);
    await userEvent.click(screen.getByRole('button', { name: button }));
    expect(await screen.findByRole('dialog', { name: title })).toBeInTheDocument();
    expect(p.toggleFollow).not.toHaveBeenCalled();
    expect(p.addComment).not.toHaveBeenCalled();
  });

  it('upvote asks for the phone', async () => {
    const p = mockPage();
    render(<IdeaPage ideaId="tok" />);
    await userEvent.click(screen.getByRole('button', { name: 'Upvote (2)' }));
    expect(await screen.findByRole('dialog', { name: 'Upvote this request' })).toBeInTheDocument();
    expect(p.vote).not.toHaveBeenCalled();
  });

  it('phone -> code -> follows as the visitor, then opens their own board', async () => {
    mockPage();
    const assign = vi.fn();
    Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true });
    svc.share.sendCode.mockResolvedValue({ sent: true });
    svc.share.verifyCode.mockResolvedValue({
      token: 'portal-jwt',
      principal: { kind: 'contact', name: 'Manager', role: 'Dealer', productId: null, canManage: false },
      boardUrl: 'https://x.test/public/feedback/board/own/FB-0042',
    });
    svc.portal.follow.mockResolvedValue({ following: true, followerCount: 3 });
    render(<IdeaPage ideaId="tok" />);
    await userEvent.click(screen.getByRole('button', { name: 'Follow' }));
    await userEvent.type(await screen.findByLabelText('Your WhatsApp number'), '012-345 0002');
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(svc.share.sendCode).toHaveBeenCalledWith('tok', '012-345 0002');
    await userEvent.type(await screen.findByLabelText('Code sent to 012-345 0002'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://x.test/public/feedback/board/own/FB-0042'));
    expect(svc.share.verifyCode).toHaveBeenCalledWith('tok', '012-345 0002', '123456');
    expect(auth.set).toHaveBeenCalledWith('portal-jwt');
    expect(svc.portal.follow).toHaveBeenCalledWith('i10');
  });

  it('an unknown number shows the product message next to the field', async () => {
    mockPage();
    const { ApiError } = await import('@/lib/api-client');
    svc.share.sendCode.mockRejectedValue(
      new ApiError("This number isn't registered with Sorento CRM. Ask your Sorento CRM contact to add you.", 404, null, null),
    );
    render(<IdeaPage ideaId="tok" />);
    await userEvent.click(screen.getByRole('button', { name: 'Follow' }));
    await userEvent.type(await screen.findByLabelText('Your WhatsApp number'), '0123450009');
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("isn't registered with Sorento CRM");
    expect(screen.getByLabelText('Your WhatsApp number')).toBeInTheDocument();
  });
});
