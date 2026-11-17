import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/** FEEDBACK-ATTACH-IMAGE fix round 1: board comment upload retry + image-only comment. */
const svc = vi.hoisted(() => ({
  get: vi.fn(),
  voters: vi.fn(),
  activity: vi.fn(),
  addComment: vi.fn(),
  uploadAttachment: vi.fn(),
  attachmentContent: vi.fn(),
}));
vi.mock('@/services/idea-portal-service', () => ({ ideaPortalService: svc }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => '/', useParams: () => ({}) }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC', formatDate: (v: string) => v, formatDateTime: (v: string) => v, formatTime: (v: string) => v,
    formatDmyDate: (v: string) => v, formatDmyDateTime: (v: string) => v,
  }),
}));
vi.mock('@/hooks/use-idea-portal', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-idea-portal')>('@/hooks/use-idea-portal');
  return {
    ...actual,
    useIdeaPortal: () => ({
      mode: 'portal',
      paths: actual.PORTAL_PATHS,
      principal: { kind: 'crm', name: 'A', role: 'Staff', productId: 'p1', canManage: false },
      signOut: vi.fn(),
    }),
  };
});

import { ApiError } from '@/lib/api-client';
import { IdeaPage } from './idea-page';

const png = (name: string) => new File(['x'], name, { type: 'image/png' });
const idea = {
  id: 'i10', ideaNumber: 'IDEA-0010', title: 'T', upvotes: 0, commentCount: 0, isMine: true, myVote: false,
  column: 'under_review', statusLabel: 'New', statusColor: 'blue', productName: 'P', submittedAt: '2026-10-02T06:31:00Z',
  problem: 'p', desiredOutcome: null, useCases: [], currentWorkaround: null, submitterFirstName: 'A', timeline: [],
  portalHidden: null, note: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }));
  svc.get.mockResolvedValue(idea);
  svc.voters.mockResolvedValue([]);
  svc.activity.mockResolvedValue([]);
  svc.addComment.mockResolvedValue({ id: 'cm1' });
});

describe('board comment uploads', () => {
  it('an image-only comment is created with an empty body and hasAttachments true', async () => {
    svc.uploadAttachment.mockResolvedValue({});
    const { container } = render(<IdeaPage ideaId="i10" />);
    await screen.findByText('T');
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, png('only.png'));
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    await waitFor(() => expect(svc.addComment).toHaveBeenCalledWith('i10', '', undefined, true));
    expect(svc.uploadAttachment.mock.calls[0][2]).toBe('cm1');
  });

  it('a failed file stays, is named, and Try again re-uploads only it to the same comment', async () => {
    svc.uploadAttachment.mockRejectedValueOnce(new Error('boom')).mockResolvedValue({});
    const { container } = render(<IdeaPage ideaId="i10" />);
    await screen.findByText('T');
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, [png('ok.png'), png('bad.png')]);
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect(await screen.findByText(/did not upload/)).toBeInTheDocument();
    expect(svc.addComment).toHaveBeenCalledTimes(1);
    svc.uploadAttachment.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(svc.uploadAttachment).toHaveBeenCalledTimes(1));
    expect(svc.uploadAttachment.mock.calls[0][2]).toBe('cm1');
    expect(svc.addComment).toHaveBeenCalledTimes(1);
  });

  it('a file or text added while a comment is still sending stays in the box', async () => {
    let finish: (v: unknown) => void = () => {};
    svc.addComment.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    svc.uploadAttachment.mockResolvedValue({});
    const { container } = render(<IdeaPage ideaId="i10" />);
    await screen.findByText('T');
    const input = () => container.querySelector('input[type="file"]') as HTMLInputElement;
    const box = screen.getByRole('textbox', { name: 'Leave a comment' });
    await userEvent.type(box, 'first');
    await userEvent.upload(input(), png('sent.png'));
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    await userEvent.type(box, ' and more');
    await userEvent.upload(input(), png('later.png'));
    finish({ id: 'cm1' });
    await waitFor(() => expect(svc.uploadAttachment).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove sent.png' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Remove later.png' })).toBeInTheDocument();
    expect(box).toHaveValue('first and more');
  });

  it('says why a file failed, lets the user drop it, and the composer returns to normal', async () => {
    svc.uploadAttachment.mockRejectedValue(new ApiError('nope', 415));
    const { container } = render(<IdeaPage ideaId="i10" />);
    await screen.findByText('T');
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement, png('x.exe'));
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect(await screen.findByText("x.exe: this file type can't be attached")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Remove x.exe' }));
    expect(await screen.findByRole('button', { name: 'Comment' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });
});
