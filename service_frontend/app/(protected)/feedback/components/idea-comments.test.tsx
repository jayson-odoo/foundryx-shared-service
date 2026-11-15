/**
 * Plan 19 (AC-19-21..24): the `IdeaComments` section. Mocked at the HOOK
 * boundary (`@/hooks/use-idea-comments` -> `useIdeaComments(ideaId)`), so the
 * component never fetches (AC-19-25).
 *
 * Chosen contract (the coder matches it):
 *  - `<IdeaComments ideaId="..." mergedChild?={boolean} />`, named export.
 *  - hook result: `{ threads: {root, replies}[], count, loading, error, add(body, parentId?),
 *    edit(commentId, body), remove(commentId) }` (`count` = live comments shown).
 *  - heading "Comments" + `data-testid="comments-count"`; thread wrapper
 *    `data-testid="comment-thread"`; reply row `data-testid="comment-reply"`;
 *    inline reply composer `data-testid="reply-composer"` (Cancel / Reply buttons).
 *  - top composer: a textbox + a "Comment" button; "Visible to submitter" badge
 *    sits next to it (AC-19-34); a `public` author gets a "Submitter" badge.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IdeaComment } from '@/types/ideation';
import { IdeationRuntimeProvider } from '@/hooks/use-ideation-runtime';
import { ideationEmbedService } from '@/services/ideation-embed-service';
import { IdeaComments } from './idea-comments';

const useIdeaComments = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-comments', () => ({
  useIdeaComments: (id: string) => useIdeaComments(id),
}));

const perms = vi.hoisted(() => ({ list: ['ideation.ideas.view', 'ideation.ideas.comment'] as string[] }));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: perms.list } }, status: 'authenticated' }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v.slice(0, 10),
    formatDateTime: (v: string) => `DT:${v.slice(0, 10)}`,
    formatTime: (v: string) => v.slice(11, 16),
  }),
}));

const aComment = (over: Partial<IdeaComment> = {}): IdeaComment => ({
  id: 'c1',
  ideaId: 'idea-1',
  parentId: null,
  authorName: 'Alice Tan',
  authorKind: 'user',
  body: 'First comment',
  isDeleted: false,
  isMine: false,
  canEdit: false,
  canDelete: false,
  createdAt: '2026-10-01T08:00:00Z',
  editedAt: null,
  ...over,
});

function hookValue(
  threads: { root: IdeaComment; replies: IdeaComment[] }[],
  over: Record<string, unknown> = {},
) {
  const live = threads.reduce(
    (n, t) => n + (t.root.isDeleted ? 0 : 1) + t.replies.filter((r) => !r.isDeleted).length,
    0,
  );
  const value = {
    threads,
    count: live,
    loading: false,
    error: null,
    add: vi.fn().mockResolvedValue(undefined),
    edit: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    ...over,
  };
  useIdeaComments.mockReturnValue(value);
  return value;
}

beforeEach(() => {
  useIdeaComments.mockReset();
  perms.list = ['ideation.ideas.view', 'ideation.ideas.comment'];
});

describe('IdeaComments - states (AC-19-21/24)', () => {
  it('loading', () => {
    hookValue([], { loading: true });
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByTestId('comments-loading')).toBeInTheDocument();
  });

  it('error', () => {
    hookValue([], { error: 'Could not load comments.' });
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByText('Could not load comments.')).toBeInTheDocument();
  });

  it('empty list reads "No comments."', () => {
    hookValue([]);
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByText('No comments.')).toBeInTheDocument();
    expect(screen.getByTestId('comments-count')).toHaveTextContent('0');
  });

  it('resolves the hook for the given idea id', () => {
    hookValue([]);
    render(<IdeaComments ideaId="idea-42" />);
    expect(useIdeaComments).toHaveBeenCalledWith('idea-42');
  });
});

describe('IdeaComments - render (AC-19-21)', () => {
  it('shows count, initials avatar, author, formatted datetime and body, oldest first', () => {
    hookValue([
      { root: aComment({ id: 'c1', body: 'First comment' }), replies: [] },
      { root: aComment({ id: 'c2', authorName: 'Bob Lee', body: 'Second comment', createdAt: '2026-10-02T08:00:00Z' }), replies: [] },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByRole('heading', { name: /^Comments/ })).toBeInTheDocument();
    expect(screen.getByTestId('comments-count')).toHaveTextContent('2');
    const threads = screen.getAllByTestId('comment-thread');
    expect(threads).toHaveLength(2);
    expect(within(threads[0]).getByText('First comment')).toBeInTheDocument();
    expect(within(threads[0]).getByText('Alice Tan')).toBeInTheDocument();
    expect(within(threads[0]).getByText('AT')).toBeInTheDocument();
    expect(within(threads[0]).getByText('DT:2026-10-01')).toBeInTheDocument();
    expect(within(threads[1]).getByText('Second comment')).toBeInTheDocument();
    expect(within(threads[1]).getByText('BL')).toBeInTheDocument();
  });

  it('shows an "edited" marker only when editedAt is set', () => {
    hookValue([
      { root: aComment({ id: 'c1', editedAt: '2026-10-01T09:00:00Z' }), replies: [] },
      { root: aComment({ id: 'c2', body: 'untouched' }), replies: [] },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    const [t1, t2] = screen.getAllByTestId('comment-thread');
    expect(within(t1).getByText(/edited/i)).toBeInTheDocument();
    expect(within(t2).queryByText(/edited/i)).not.toBeInTheDocument();
  });

  it('renders the body as PLAIN TEXT with whitespace preserved, never as HTML', () => {
    hookValue([{ root: aComment({ body: '<b>bold</b> <img src=x onerror=alert(1)>\nline two' }), replies: [] }]);
    const { container } = render(<IdeaComments ideaId="idea-1" />);
    const body = screen.getByText(/<b>bold<\/b>/);
    expect(body.className).toMatch(/whitespace-pre/);
    expect(container.querySelector('b')).toBeNull();
    expect(container.querySelector('img[src="x"]')).toBeNull();
  });

  it('public comments carry a "Submitter" badge (AC-19-34)', () => {
    hookValue([
      { root: aComment({ id: 'c1', authorKind: 'public', authorName: 'Jayson' }), replies: [] },
      { root: aComment({ id: 'c2', authorKind: 'user', authorName: 'Staff Sam', body: 'by staff' }), replies: [] },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    const [t1, t2] = screen.getAllByTestId('comment-thread');
    expect(within(t1).getByText('Submitter')).toBeInTheDocument();
    expect(within(t2).queryByText('Submitter')).not.toBeInTheDocument();
  });

  it('a deleted comment with live replies shows "Comment deleted" (no body, no author)', () => {
    hookValue([
      {
        root: aComment({ id: 'c1', isDeleted: true, body: null, authorName: null }),
        replies: [aComment({ id: 'r1', parentId: 'c1', body: 'still here', authorName: 'Bob Lee' })],
      },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByText('Comment deleted')).toBeInTheDocument();
    expect(screen.getByText('still here')).toBeInTheDocument();
    expect(screen.getByTestId('comments-count')).toHaveTextContent('1');
  });
});

describe('IdeaComments - composer (AC-19-21/24/34)', () => {
  it('Comment is disabled while empty or whitespace, enabled with text', async () => {
    const user = userEvent.setup();
    hookValue([]);
    render(<IdeaComments ideaId="idea-1" />);
    const btn = screen.getByRole('button', { name: 'Comment' });
    expect(btn).toBeDisabled();
    await user.type(screen.getByRole('textbox'), '   ');
    expect(btn).toBeDisabled();
    await user.type(screen.getByRole('textbox'), 'hello');
    expect(btn).toBeEnabled();
  });

  it('posts the trimmed body with no parent, then clears the box', async () => {
    const user = userEvent.setup();
    const v = hookValue([]);
    render(<IdeaComments ideaId="idea-1" />);
    await user.type(screen.getByRole('textbox'), ' hello world ');
    await user.click(screen.getByRole('button', { name: 'Comment' }));
    expect(v.add).toHaveBeenCalledTimes(1);
    expect(String(v.add.mock.calls[0][0]).trim()).toBe('hello world');
    expect(v.add.mock.calls[0][1] ?? null).toBeNull();
    expect(screen.getByRole('textbox')).toHaveValue('');
  });

  it('shows the "Visible to submitter" badge next to the Comment button', () => {
    hookValue([]);
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.getByText('Visible to submitter')).toBeInTheDocument();
  });

  it('hides the composer when the operator lacks ideation.ideas.comment (list still shows)', () => {
    perms.list = ['ideation.ideas.view'];
    hookValue([{ root: aComment(), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" />);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Comment' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();
    expect(screen.getByText('First comment')).toBeInTheDocument();
  });

  it('hides the composer on a merged child but keeps reading', () => {
    hookValue([{ root: aComment(), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" mergedChild />);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();
    expect(screen.getByText('First comment')).toBeInTheDocument();
  });

  it('embed mode shows the composer without any operator permission', () => {
    perms.list = [];
    hookValue([]);
    render(
      <IdeationRuntimeProvider
        runtime={{
          mode: 'embed',
          service: ideationEmbedService,
          paths: { listHref: '/embed/ideas', formHref: (id: string) => `/embed/ideas/${id}`, newHref: '/embed/ideas/new' },
        }}
      >
        <IdeaComments ideaId="idea-1" />
      </IdeationRuntimeProvider>,
    );
    expect(screen.getByRole('textbox')).toBeInTheDocument();
  });
});

describe('IdeaComments - replies (AC-19-22)', () => {
  const thread = {
    root: aComment({ id: 'c1' }),
    replies: [aComment({ id: 'r1', parentId: 'c1', body: 'a reply', authorName: 'Bob Lee' })],
  };

  it('renders replies inside the thread, as reply rows (indented)', () => {
    hookValue([thread]);
    render(<IdeaComments ideaId="idea-1" />);
    const t = screen.getByTestId('comment-thread');
    const reply = within(t).getByTestId('comment-reply');
    expect(within(reply).getByText('a reply')).toBeInTheDocument();
    expect(within(t).getAllByTestId('comment-reply')).toHaveLength(1);
  });

  it('Reply opens an inline composer in that thread; Cancel closes it', async () => {
    const user = userEvent.setup();
    hookValue([thread]);
    render(<IdeaComments ideaId="idea-1" />);
    const t = screen.getByTestId('comment-thread');
    expect(within(t).queryByTestId('reply-composer')).not.toBeInTheDocument();
    await user.click(within(t).getAllByRole('button', { name: 'Reply' })[0]);
    const composer = within(t).getByTestId('reply-composer');
    expect(within(composer).getByRole('textbox')).toBeInTheDocument();
    await user.click(within(composer).getByRole('button', { name: 'Cancel' }));
    expect(within(t).queryByTestId('reply-composer')).not.toBeInTheDocument();
  });

  it('replying to a top-level comment posts add(body, rootId)', async () => {
    const user = userEvent.setup();
    const v = hookValue([thread]);
    render(<IdeaComments ideaId="idea-1" />);
    const t = screen.getByTestId('comment-thread');
    // the first Reply control belongs to the root comment
    await user.click(within(t).getAllByRole('button', { name: 'Reply' })[0]);
    const composer = within(t).getByTestId('reply-composer');
    await user.type(within(composer).getByRole('textbox'), 'answer');
    await user.click(within(composer).getByRole('button', { name: 'Reply' }));
    expect(v.add).toHaveBeenCalledWith('answer', 'c1');
  });

  it('replying to a REPLY posts to the top-level parent, not the reply', async () => {
    const user = userEvent.setup();
    const v = hookValue([thread]);
    render(<IdeaComments ideaId="idea-1" />);
    const reply = screen.getByTestId('comment-reply');
    await user.click(within(reply).getByRole('button', { name: 'Reply' }));
    const composer = screen.getByTestId('reply-composer');
    await user.type(within(composer).getByRole('textbox'), 'nested');
    await user.click(within(composer).getByRole('button', { name: 'Reply' }));
    expect(v.add).toHaveBeenCalledWith('nested', 'c1');
  });
});

describe('IdeaComments - edit and delete (AC-19-23)', () => {
  it('Edit / Delete show only when canEdit / canDelete', () => {
    hookValue([
      { root: aComment({ id: 'c1', canEdit: true, canDelete: true, isMine: true }), replies: [] },
      { root: aComment({ id: 'c2', body: 'other', canEdit: false, canDelete: true }), replies: [] },
      { root: aComment({ id: 'c3', body: 'locked', canEdit: false, canDelete: false }), replies: [] },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    const [t1, t2, t3] = screen.getAllByTestId('comment-thread');
    expect(within(t1).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(within(t1).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(within(t2).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(within(t2).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(within(t3).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(within(t3).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('Edit swaps the body for a prefilled textarea; Cancel restores; Save calls edit(id, body)', async () => {
    const user = userEvent.setup();
    const v = hookValue([{ root: aComment({ id: 'c1', canEdit: true }), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" />);
    const t = screen.getByTestId('comment-thread');
    await user.click(within(t).getByRole('button', { name: 'Edit' }));
    const box = within(t).getByDisplayValue('First comment');
    await user.click(within(t).getByRole('button', { name: 'Cancel' }));
    expect(within(t).queryByDisplayValue('First comment')).not.toBeInTheDocument();
    expect(v.edit).not.toHaveBeenCalled();
    expect(box).not.toBeInTheDocument();

    await user.click(within(t).getByRole('button', { name: 'Edit' }));
    const again = within(t).getByDisplayValue('First comment');
    await user.clear(again);
    await user.type(again, 'Edited text');
    await user.click(within(t).getByRole('button', { name: 'Save comment' }));
    expect(v.edit).toHaveBeenCalledWith('c1', 'Edited text');
  });

  it('Delete asks for confirmation (AlertDialog) and only then calls remove(id)', async () => {
    const user = userEvent.setup();
    const v = hookValue([{ root: aComment({ id: 'c1', canDelete: true }), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" />);
    await user.click(within(screen.getByTestId('comment-thread')).getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(v.remove).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(v.remove).toHaveBeenCalledWith('c1');
  });

  it('cancelling the confirmation deletes nothing', async () => {
    const user = userEvent.setup();
    const v = hookValue([{ root: aComment({ id: 'c1', canDelete: true }), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" />);
    await user.click(within(screen.getByTestId('comment-thread')).getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(v.remove).not.toHaveBeenCalled();
  });
});

describe('IdeaComments - reply inside a thread whose root is deleted (AC-19-40)', () => {
  it('Reply on a reply posts the CLICKED reply id as parentId (backend normalises it)', async () => {
    const user = userEvent.setup();
    const v = hookValue([
      {
        root: aComment({ id: 'c1', isDeleted: true, body: null, authorName: null }),
        replies: [aComment({ id: 'r1', parentId: 'c1', body: 'live reply', authorName: 'Bob Lee' })],
      },
    ]);
    render(<IdeaComments ideaId="idea-1" />);
    await user.click(within(screen.getByTestId('comment-reply')).getByRole('button', { name: 'Reply' }));
    const composer = screen.getByTestId('reply-composer');
    await user.type(within(composer).getByRole('textbox'), 'answer');
    await user.click(within(composer).getByRole('button', { name: 'Reply' }));
    expect(v.add).toHaveBeenCalledWith('answer', 'r1');
  });
});

describe('IdeaComments - delete dialog accessibility (AC-19-43)', () => {
  it('the confirmation alertdialog has an accessible description', async () => {
    const user = userEvent.setup();
    hookValue([{ root: aComment({ id: 'c1', canDelete: true }), replies: [] }]);
    render(<IdeaComments ideaId="idea-1" />);
    await user.click(within(screen.getByTestId('comment-thread')).getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    const id = dialog.getAttribute('aria-describedby');
    expect(id).toBeTruthy();
    expect(document.getElementById(id as string)?.textContent?.trim()).toBeTruthy();
  });
});
