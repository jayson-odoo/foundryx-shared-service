'use client';

import { useState } from 'react';
import { MessageSquare, Pencil, Reply, Trash2 } from 'lucide-react';
import type { IdeaComment, IdeaCommentThread } from '@/types/ideation';
import { cn } from '@/lib/utils';
import { useDatetime } from '@/hooks/use-datetime';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Textarea } from '@/components/ui/textarea';
import { UserAvatar } from '@/components/platform/user-avatar';

export interface IdeaCommentsViewProps {
  threads: IdeaCommentThread[];
  count: number;
  loading: boolean;
  error: string | null;
  /** Whether the viewer may post (composer + Reply). Reading is always allowed. */
  canComment: boolean;
  onAdd: (body: string, parentId?: string) => Promise<void>;
  /** Omit on a surface where comments cannot be edited (the public page). */
  onEdit?: (commentId: string, body: string) => Promise<void>;
  /** Omit on a surface where comments cannot be deleted (the public page). */
  onRemove?: (commentId: string) => Promise<void>;
  /** Operator / embed composer: staff comments are visible to the submitter. */
  visibleToSubmitter?: boolean;
}

const linkButton =
  'inline-flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground';

// AC-19-23 pins the inline editor's buttons as "Cancel" / "Save": the noun is the
// comment being edited right above, so the label stays this short.
const EDIT_SAVE_LABEL = 'Save';

function CommentBody({ text }: { text: string }) {
  // Plain text only: a React text node, whitespace preserved. Never HTML.
  return <p className="whitespace-pre-wrap break-words text-sm">{text}</p>;
}

interface CommentRowProps {
  comment: IdeaComment;
  topLevel: boolean;
  canComment: boolean;
  editing: boolean;
  onReply: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (body: string) => Promise<void>;
  onAskDelete: () => void;
  canEditHere: boolean;
  canDeleteHere: boolean;
}

function CommentRow({
  comment,
  topLevel,
  canComment,
  editing,
  onReply,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onAskDelete,
  canEditHere,
  canDeleteHere,
}: CommentRowProps) {
  const { formatDateTime } = useDatetime();
  if (comment.isDeleted) {
    return (
      <div className="flex items-center gap-2 py-1 text-sm italic text-muted-foreground">
        Comment deleted
      </div>
    );
  }

  const author = comment.authorName ?? '';
  return (
    <div className="flex gap-3">
      <UserAvatar
        user={{ name: author, email: author, avatar: null }}
        size={topLevel ? 'md' : 'sm'}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-sm font-semibold">{author}</span>
          {comment.authorKind === 'public' && (
            <Badge variant="secondary" appearance="light" size="sm">
              Submitter
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {formatDateTime(comment.createdAt)}
          </span>
          {comment.editedAt && (
            <span className="text-xs text-muted-foreground">edited</span>
          )}
        </div>
        {editing ? (
          <CommentEditor
            initial={comment.body ?? ''}
            onCancel={onCancelEdit}
            onSave={onSaveEdit}
          />
        ) : (
          <>
            <CommentBody text={comment.body ?? ''} />
            <div className="mt-1 flex flex-wrap items-center gap-3">
              {canComment && (
                <button
                  type="button"
                  className={cn(PRESSED_CLASS, linkButton)}
                  onClick={onReply}
                >
                  <Reply className="size-3.5" />
                  Reply
                </button>
              )}
              {canEditHere && (
                <button
                  type="button"
                  className={cn(PRESSED_CLASS, linkButton)}
                  onClick={onStartEdit}
                >
                  <Pencil className="size-3.5" />
                  Edit
                </button>
              )}
              {canDeleteHere && (
                <button
                  type="button"
                  className={cn(PRESSED_CLASS, linkButton)}
                  onClick={onAskDelete}
                >
                  <Trash2 className="size-3.5" />
                  Delete
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CommentEditor({
  initial,
  onCancel,
  onSave,
}: {
  initial: string;
  onCancel: () => void;
  onSave: (body: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    const text = draft.trim();
    if (!text) return;
    setSaving(true);
    try {
      await onSave(text);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="mt-1.5 flex flex-col gap-2">
      <Textarea
        rows={3}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => void save()}
          disabled={saving || !draft.trim()}
        >
          {EDIT_SAVE_LABEL}
        </Button>
      </div>
    </div>
  );
}

function Composer({
  placeholder,
  submitLabel,
  onSubmit,
  onCancel,
  badge,
  testId,
  autoFocus,
}: {
  placeholder?: string;
  submitLabel: string;
  onSubmit: (body: string) => Promise<void>;
  onCancel?: () => void;
  badge?: boolean;
  testId?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const empty = !text.trim();

  const submit = async () => {
    if (empty || busy) return;
    setBusy(true);
    try {
      await onSubmit(text.trim());
      setText('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <Textarea
        rows={3}
        value={text}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        {badge && (
          <Badge variant="secondary" appearance="light" size="sm">
            Visible to submitter
          </Badge>
        )}
        {onCancel && (
          <Button
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </Button>
        )}
        <Button
          variant="primary"
          size="sm"
          onClick={() => void submit()}
          disabled={empty || busy}
        >
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}

/**
 * The shared comments section (plan 19, AC-19-21..24 and 33): a composer above the
 * thread list, replies one level deep, edit / delete / reply controls gated by
 * the per-comment flags. Pure presentation - the operator / embed section and the
 * public status page each wire their own hook into it.
 */
export function IdeaCommentsView({
  threads,
  count,
  loading,
  error,
  canComment,
  onAdd,
  onEdit,
  onRemove,
  visibleToSubmitter = false,
}: IdeaCommentsViewProps) {
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const rowFor = (comment: IdeaComment, rootId: string, topLevel: boolean) => (
    <CommentRow
      key={comment.id}
      comment={comment}
      topLevel={topLevel}
      canComment={canComment}
      editing={editingId === comment.id}
      onReply={() => setReplyTo(rootId)}
      onStartEdit={() => setEditingId(comment.id)}
      onCancelEdit={() => setEditingId(null)}
      onSaveEdit={async (body) => {
        await onEdit?.(comment.id, body);
        setEditingId(null);
      }}
      onAskDelete={() => setDeleteId(comment.id)}
      canEditHere={Boolean(onEdit) && comment.canEdit}
      canDeleteHere={Boolean(onRemove) && comment.canDelete}
    />
  );

  return (
    <section className="flex flex-col gap-4 pt-4">
      <h3 className="flex items-center gap-2 font-heading text-base font-semibold">
        <MessageSquare className="size-4 text-muted-foreground" />
        Comments
        <span
          data-testid="comments-count"
          className="rounded-full bg-muted px-2 text-xs font-medium tabular-nums text-muted-foreground"
        >
          {count}
        </span>
      </h3>

      {canComment && (
        <Composer
          placeholder="Write a comment"
          submitLabel="Comment"
          badge={visibleToSubmitter}
          onSubmit={(body) => onAdd(body)}
        />
      )}

      {loading ? (
        <p
          data-testid="comments-loading"
          className="text-sm text-muted-foreground"
        >
          Loading comments
        </p>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : threads.length === 0 ? (
        <p className="text-sm text-muted-foreground">No comments.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {threads.map((thread) => (
            <div
              key={thread.root.id}
              data-testid="comment-thread"
              className="flex flex-col gap-3"
            >
              {rowFor(thread.root, thread.root.id, true)}
              {thread.replies.length > 0 && (
                <div
                  className={cn(
                    'flex flex-col gap-3 border-s ps-4 ms-4 sm:ms-5',
                  )}
                >
                  {thread.replies.map((reply) => (
                    <div key={reply.id} data-testid="comment-reply">
                      {rowFor(reply, thread.root.id, false)}
                    </div>
                  ))}
                </div>
              )}
              {canComment && replyTo === thread.root.id && (
                <div className="ms-4 ps-4 sm:ms-5">
                  <Composer
                    testId="reply-composer"
                    submitLabel="Reply"
                    autoFocus
                    onCancel={() => setReplyTo(null)}
                    onSubmit={async (body) => {
                      await onAdd(body, thread.root.id);
                      setReplyTo(null);
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <AlertDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this comment?</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const id = deleteId;
                setDeleteId(null);
                if (id) void onRemove?.(id);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
