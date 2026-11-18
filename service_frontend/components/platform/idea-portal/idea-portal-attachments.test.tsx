import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PortalActivity, PortalIdea } from '@/types/idea-portal';

/**
 * FEEDBACK-ATTACH-IMAGE AC-A-23/24/25. Service mocked at the service boundary
 * (`ideaPortalService.uploadAttachment(id, file, commentId?)`, `attachmentContent(path)`).
 * Thumbnails are buttons named after the file (AttachmentThumbs); the file input is the
 * first `input[type=file]` in the form/composer.
 */
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
    formatDmyDate: (v: string) => v.slice(0, 10),
    formatDmyDateTime: (v: string) => `DT:${v.slice(0, 10)}`,
  }),
}));
vi.mock('@/hooks/use-branding', () => ({
  useTenantBranding: () => ({
    branding: { isBranded: true, tenantName: 'T', appName: null, slogan: null, logoUrl: null, faviconUrl: null, illustrationUrl: null, tokens: null, version: 0 },
    isResolved: true,
  }),
}));

const svc = vi.hoisted(() => ({
  submit: vi.fn(),
  products: vi.fn(),
  uploadAttachment: vi.fn(),
  attachmentContent: vi.fn(),
}));
vi.mock('@/services/idea-portal-service', () => ({ ideaPortalService: svc }));

const pageHook = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-portal', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-idea-portal')>('@/hooks/use-idea-portal');
  return {
    ...actual,
    useIdeaPortal: () => ({
      mode: 'portal',
      paths: actual.PORTAL_PATHS,
      principal: { kind: 'crm', name: 'Aiman', role: 'Staff', productId: 'p1', canManage: false },
      signOut: vi.fn(),
    }),
    usePortalIdeaPage: (id: string) => pageHook(id),
  };
});

import { IdeaPage } from './idea-page';
import { SubmitIdeaForm } from './submit-idea-form';

const att = (id: string, name: string, kind = 'file') => ({
  id, kind, name, sizeBytes: 10, contentPath: `/portal/ideas/i10/attachments/${id}/content`, url: '',
});
const png = (name: string) => new File(['x'], name, { type: 'image/png' });
const fileInput = (root: HTMLElement) => {
  const el = root.querySelector('input[type="file"]') as HTMLInputElement | null;
  expect(el, 'a file input must exist').not.toBeNull();
  return el as HTMLInputElement;
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
  svc.products.mockResolvedValue([{ id: 'p1', name: 'Product' }]);
  svc.submit.mockResolvedValue({ id: 'new1' });
  svc.uploadAttachment.mockResolvedValue(att('a1', 'shot.png'));
  svc.attachmentContent.mockResolvedValue(new Blob(['x'], { type: 'image/png' }));
});

async function fillSubmit(container: HTMLElement) {
  await userEvent.type(screen.getByLabelText(/^Title/), 'Broken screen');
  await userEvent.type(screen.getByLabelText(/Business problem/), 'It crashes');
  return fileInput(container);
}

describe('SubmitIdeaForm attachments (AC-A-23)', () => {
  it('creates the item first, then uploads each file to it, then opens it', async () => {
    const { container } = render(<SubmitIdeaForm />);
    const input = await fillSubmit(container);
    await userEvent.upload(input, [png('one.png'), png('two.png')]);
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(svc.uploadAttachment).toHaveBeenCalledTimes(2));
    expect(svc.submit).toHaveBeenCalledTimes(1);
    expect(svc.submit.mock.invocationCallOrder[0]).toBeLessThan(svc.uploadAttachment.mock.invocationCallOrder[0]);
    expect(svc.uploadAttachment.mock.calls.map((c) => c[0])).toEqual(['new1', 'new1']);
    expect(svc.uploadAttachment.mock.calls.map((c) => (c[1] as File).name)).toEqual(['one.png', 'two.png']);
    await waitFor(() => expect(push).toHaveBeenCalled());
  });

  it('a failed file is named with Try again; the item still exists', async () => {
    svc.uploadAttachment.mockRejectedValueOnce(new Error('boom')).mockResolvedValue(att('a2', 'bad.png'));
    const { container } = render(<SubmitIdeaForm />);
    const input = await fillSubmit(container);
    await userEvent.upload(input, [png('bad.png')]);
    await userEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/bad\.png/)).toBeInTheDocument();
    const retry = screen.getByRole('button', { name: /try again/i });
    expect(svc.submit).toHaveBeenCalledTimes(1);
    await userEvent.click(retry);
    await waitFor(() => expect(svc.uploadAttachment).toHaveBeenCalledTimes(2));
    expect(svc.submit).toHaveBeenCalledTimes(1);
  });
});

const idea: PortalIdea = {
  id: 'i10', ideaNumber: 'IDEA-0010', title: 'Order status', upvotes: 0, commentCount: 1, isMine: true,
  myVote: false, column: 'under_review', statusLabel: 'New', statusColor: 'blue', productName: 'P',
  submittedAt: '2026-10-02T06:31:00Z', problem: 'It breaks.', desiredOutcome: null, useCases: [],
  currentWorkaround: null, submitterFirstName: 'Aiman', timeline: [], portalHidden: null, note: null,
  attachments: [att('r1', 'report-notes.pdf')],
} as PortalIdea;
const comment = {
  id: 'c1', ideaId: 'i10', parentId: null, authorName: 'Nadia', authorKind: 'user', authorRole: 'Staff',
  body: 'See attached', isDeleted: false, isMine: true, canEdit: false, canDelete: true,
  createdAt: '2026-10-10T08:40:00Z', editedAt: null, likeCount: 0, likedByMe: false,
  attachments: [att('k1', 'comment-spec.pdf')],
};
const base = { by: null, source: null, fromLabel: null, toLabel: null, toColor: null, comment: null, replies: [], commentId: null };
const activity: PortalActivity[] = [
  { ...base, kind: 'comment', at: '2026-10-10T08:40:00Z', comment } as PortalActivity,
];
const q = <T,>(data: T) => ({ data, loading: false, error: null, notFound: false, reload: vi.fn(), setData: vi.fn() });
function mockPage() {
  const p = {
    idea: q(idea), voters: q([]), activity: q(activity), order: 'desc' as const, setOrder: vi.fn(),
    vote: vi.fn(), addComment: vi.fn().mockResolvedValue([]), deleteComment: vi.fn(), likeComment: vi.fn(),
    setHidden: vi.fn(), setNote: vi.fn(), actionError: null as string | null,
  };
  pageHook.mockReturnValue(p);
  return p;
}

describe('IdeaPage attachments (AC-A-24/25)', () => {
  it('the Comment button is enabled with only a file, and the file goes to addComment', async () => {
    const p = mockPage();
    const { container } = render(<IdeaPage ideaId="i10" />);
    const send = screen.getByRole('button', { name: 'Comment' });
    expect(send).toBeDisabled();
    const file = png('only.png');
    await userEvent.upload(fileInput(container), file);
    expect(send).toBeEnabled();
    await userEvent.click(send);
    expect(p.addComment).toHaveBeenCalledTimes(1);
    expect(p.addComment.mock.calls[0].flat(2)).toContain(file);
  });

  it('report thumbnails render under the fields', () => {
    mockPage();
    render(<IdeaPage ideaId="i10" />);
    const fields = screen.getByTestId('portal-idea-fields');
    expect(within(fields).getByRole('button', { name: /report-notes\.pdf/ })).toBeInTheDocument();
  });

  it('comment thumbnails render under the comment and open the shared preview', async () => {
    mockPage();
    render(<IdeaPage ideaId="i10" />);
    const c = screen.getAllByTestId('portal-comment')[0];
    await userEvent.click(within(c).getByRole('button', { name: /comment-spec\.pdf/ }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download/i })).toBeInTheDocument();
  });
});
