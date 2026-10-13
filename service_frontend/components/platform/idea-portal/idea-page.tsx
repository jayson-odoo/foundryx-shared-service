'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Heart, Reply, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeaPortal, usePortalIdeaPage } from '@/hooks/use-idea-portal';
import { IdeaStatusTimeline } from '@/app/(public)/public/ideas/[token]/components/idea-status-timeline';
import { colorToHex } from '@/components/platform/status-badge';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { PortalActivity, PortalComment, PortalIdea, PortalVoter } from '@/types/idea-portal';
import { PortalStatusPill } from './portal-status-pill';
import { PortalLoading, PortalMessage } from './portal-states';
import { UpvoteBox } from './upvote-box';

const ORDER_OPTIONS = [
  { value: 'desc', label: 'Newest first' },
  { value: 'asc', label: 'Oldest first' },
];
const MAX_COMMENT = 2000;

function initials(name: string | null): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase();
}

function Avatar({ name, small }: { name: string | null; small?: boolean }) {
  return (
    <span
      aria-hidden
      className={
        small
          ? 'flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-2xs font-semibold'
          : 'flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold'
      }
    >
      {initials(name)}
    </span>
  );
}

function Composer({
  onSubmit,
  placeholder,
  submitLabel,
  autoFocus,
}: {
  onSubmit: (body: string) => Promise<void>;
  placeholder: string;
  submitLabel: string;
  autoFocus?: boolean;
}) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const trimmed = body.trim();
  const send = async () => {
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await onSubmit(trimmed);
      setBody('');
    } catch {
      // the hook surfaces the error
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <Textarea
        rows={3}
        value={body}
        maxLength={MAX_COMMENT}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="flex justify-end">
        <Button size="sm" disabled={!trimmed || busy} onClick={send}>
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}

function CommentItem({
  c,
  onLike,
  onDelete,
  onReply,
  small,
}: {
  c: PortalComment;
  onLike: (id: string) => void;
  onDelete: (id: string) => void;
  onReply?: () => void;
  small?: boolean;
}) {
  const { formatDateTime } = useDatetime();
  if (c.isDeleted) {
    return <p className="text-sm text-muted-foreground italic">Comment deleted</p>;
  }
  return (
    <div className="flex min-w-0 gap-3" data-testid="portal-comment">
      <Avatar name={c.authorName} small={small} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="font-semibold">{c.authorName ?? c.authorRole}</span>
          <span className="rounded bg-muted px-1.5 text-xs">{c.authorRole}</span>
          <span className="text-xs text-muted-foreground">{formatDateTime(c.createdAt)}</span>
        </div>
        <p className="mt-1 break-words whitespace-pre-wrap">{c.body}</p>
        <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
          <button
            type="button"
            aria-pressed={c.likedByMe}
            aria-label={c.likedByMe ? 'Unlike' : 'Like'}
            onClick={() => onLike(c.id)}
            className={c.likedByMe ? 'inline-flex items-center gap-1 text-primary' : 'inline-flex items-center gap-1 hover:text-foreground'}
          >
            <Heart className="size-3.5" aria-hidden />
            {c.likeCount}
          </button>
          {onReply && (
            <button type="button" onClick={onReply} className="inline-flex items-center gap-1 hover:text-foreground">
              <Reply className="size-3.5" aria-hidden />
              Reply
            </button>
          )}
          {c.canDelete && (
            <button
              type="button"
              aria-label="Delete comment"
              onClick={() => onDelete(c.id)}
              className="inline-flex items-center gap-1 hover:text-destructive"
            >
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ActivityItem({
  e,
  onLike,
  onDelete,
  onReply,
}: {
  e: PortalActivity;
  onLike: (id: string) => void;
  onDelete: (id: string) => void;
  onReply: (parentId: string, body: string) => Promise<void>;
}) {
  const { formatDateTime, formatDate } = useDatetime();
  const [replying, setReplying] = useState(false);
  if (e.kind === 'comment' && e.comment) {
    const top = e.comment;
    return (
      <li className="flex flex-col gap-3" data-kind="comment">
        <CommentItem c={top} onLike={onLike} onDelete={onDelete} onReply={top.isDeleted ? undefined : () => setReplying((r) => !r)} />
        {(e.replies.length > 0 || replying) && (
          <div className="ml-10 flex flex-col gap-3 border-l border-border pl-3">
            {e.replies.map((r) => (
              <CommentItem key={r.id} c={r} small onLike={onLike} onDelete={onDelete} />
            ))}
            {replying && (
              <Composer
                autoFocus
                placeholder="Write a reply"
                submitLabel="Send reply"
                onSubmit={async (body) => {
                  await onReply(top.id, body);
                  setReplying(false);
                }}
              />
            )}
          </div>
        )}
      </li>
    );
  }
  let text: React.ReactNode = null;
  let dot = colorToHex('gray');
  let when = formatDateTime(e.at);
  if (e.kind === 'status_changed') {
    dot = colorToHex(e.toColor);
    text = (
      <>
        <b>Status changed</b> {e.fromLabel ? `${e.fromLabel} → ` : ''}
        <span className="font-medium">{e.toLabel}</span>
      </>
    );
  } else if (e.kind === 'submitted') {
    dot = colorToHex('blue');
    text = (
      <>
        <b>Idea submitted</b>
        {e.by ? ` by ${e.by}` : ''}
        {e.source === 'whatsapp' ? ' over WhatsApp' : ''}
      </>
    );
  } else if (e.kind === 'upvotes') {
    const named = e.names.join(', ');
    const others = (e.count ?? 0) - e.names.length;
    text = (
      <>
        <b>{named || `${e.count} ${e.count === 1 ? 'person' : 'people'}`}</b>
        {named && others > 0 ? ` and ${others} ${others === 1 ? 'other' : 'others'}` : ''} upvoted
      </>
    );
    when = formatDate(e.at);
  } else if (e.kind === 'comment_like') {
    text = (
      <>
        <b>{e.by ?? 'Someone'}</b> liked a comment
      </>
    );
  }
  return (
    <li className="flex gap-3" data-kind={e.kind}>
      <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ backgroundColor: dot }} aria-hidden />
      <div>
        <div>{text}</div>
        <div className="text-xs text-muted-foreground">{when}</div>
      </div>
    </li>
  );
}

function Fields({ idea }: { idea: PortalIdea }) {
  const rows: { label: string; value: string | null; list?: boolean }[] = [
    { label: 'Business problem', value: idea.problem },
    { label: 'Desired outcome', value: idea.desiredOutcome },
    { label: 'Use cases', value: idea.useCases, list: true },
    { label: 'Current workaround', value: idea.currentWorkaround },
  ];
  const shown = rows.filter((r) => r.value && r.value.trim());
  if (shown.length === 0) return null;
  return (
    <Card data-testid="portal-idea-fields">
      <CardContent className="py-4">
        <dl className="flex flex-col gap-4 text-sm">
          {shown.map((r) => (
            <div key={r.label}>
              <dt className="font-medium">{r.label}</dt>
              <dd className="mt-1 break-words whitespace-pre-wrap text-foreground/80">
                {r.list ? (
                  <ul className="list-disc pl-5">
                    {(r.value ?? '')
                      .split(/\r?\n/)
                      .map((l) => l.replace(/^\s*[-*•]\s*/, '').trim())
                      .filter(Boolean)
                      .map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                  </ul>
                ) : (
                  r.value
                )}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function Voters({ voters }: { voters: PortalVoter[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? voters : voters.slice(0, 8);
  return (
    <Card data-testid="portal-voters">
      <CardContent className="py-4">
        <h3 className="text-sm font-semibold">
          Voters <span className="text-muted-foreground">{voters.length}</span>
        </h3>
        {voters.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No votes yet</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {shown.map((v, i) => (
              <li key={i} className="flex items-center gap-2">
                <Avatar name={v.name ?? v.role} small />
                <span>{v.isMe ? 'You' : (v.name ?? v.role)}</span>
                <span className="ml-auto text-xs text-muted-foreground">{v.role}</span>
              </li>
            ))}
          </ul>
        )}
        {!all && voters.length > shown.length && (
          <Button mode="link" size="sm" className="mt-3" onClick={() => setAll(true)}>
            Show all {voters.length}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function NoteEditor({ note, onSave }: { note: string | null; onSave: (note: string | null) => void }) {
  const [value, setValue] = useState(note ?? '');
  const dirty = value.trim() !== (note ?? '');
  return (
    <Card data-testid="portal-note-editor">
      <CardContent className="flex flex-col gap-2 py-4">
        <Label htmlFor="portal-note">Changelog note</Label>
        <Textarea id="portal-note" rows={2} maxLength={500} value={value} onChange={(e) => setValue(e.target.value)} />
        <div className="flex justify-end">
          <Button size="sm" variant="outline" disabled={!dirty} onClick={() => onSave(value.trim() || null)}>
            Save note
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export interface IdeaPageProps {
  ideaId: string;
}

/** The idea (card) page: status, upvote box, the four fields, comments,
 * activity feed (newest first), "where is it" timeline, voters. */
export function IdeaPage({ ideaId }: IdeaPageProps) {
  const { paths, principal } = useIdeaPortal();
  const { formatDate } = useDatetime();
  const page = usePortalIdeaPage(ideaId);
  const idea = page.idea.data;

  if (page.idea.loading && !idea) return <PortalLoading />;
  if (page.idea.notFound) return <PortalMessage text="This idea isn’t available." />;
  if (!idea) return <PortalMessage text="This idea could not be loaded." />;

  const onAction = (p: Promise<void>) => p.catch(() => toast.error(page.actionError ?? 'Something went wrong.'));

  return (
    <>
      <Link href={paths.roadmap} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden />
        Roadmap
      </Link>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="flex min-w-0 flex-col gap-5">
          <div className="flex gap-4" data-testid="portal-idea-hero">
            <UpvoteBox size="lg" count={idea.upvotes} voted={idea.myVote} onVote={() => onAction(page.vote())} />
            <div className="min-w-0">
              {idea.ideaNumber && <p className="text-sm font-medium text-muted-foreground">{idea.ideaNumber}</p>}
              <h1 className="font-heading text-xl font-semibold break-words sm:text-2xl">{idea.title}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                {idea.statusLabel && <PortalStatusPill label={idea.statusLabel} color={idea.statusColor} />}
                {idea.submitterFirstName && <span>Submitted by {idea.submitterFirstName}</span>}
                {idea.submittedAt && <span>{formatDate(idea.submittedAt)}</span>}
                {idea.isMine && (
                  <span className="rounded-full border border-primary px-2 py-0.5 text-xs text-primary">Your idea</span>
                )}
              </div>
            </div>
          </div>

          {principal.canManage && idea.portalHidden !== null && (
            <div className="flex items-center gap-2">
              <Switch
                id="portal-hidden"
                checked={Boolean(idea.portalHidden)}
                onCheckedChange={(v) => onAction(page.setHidden(Boolean(v)))}
              />
              <Label htmlFor="portal-hidden">Hide from portal</Label>
            </div>
          )}

          {principal.canManage && idea.column === 'complete' && (
            <NoteEditor key={idea.note ?? ''} note={idea.note} onSave={(n) => onAction(page.setNote(n))} />
          )}

          <Fields idea={idea} />

          <Card>
            <CardContent className="py-4">
              <Composer
                placeholder="Leave a comment"
                submitLabel="Comment"
                onSubmit={(body) => page.addComment(body)}
              />
              {page.actionError && <p className="mt-2 text-sm text-destructive">{page.actionError}</p>}
            </CardContent>
          </Card>

          <section className="flex flex-col gap-3" aria-label="Activity">
            <div className="flex items-center gap-2">
              <h2 className="font-heading font-semibold">Activity</h2>
              <SearchSelect
                className="ml-auto w-40"
                ariaLabel="Activity order"
                options={ORDER_OPTIONS}
                value={page.order}
                onChange={(v) => page.setOrder(v === 'asc' ? 'asc' : 'desc')}
              />
            </div>
            <ol className="flex flex-col gap-4 text-sm" data-testid="portal-activity">
              {(page.activity.data ?? []).map((e, i) => (
                <ActivityItem
                  key={`${e.kind}-${e.comment?.id ?? e.at}-${i}`}
                  e={e}
                  onLike={(id) => onAction(page.likeComment(id))}
                  onDelete={(id) => onAction(page.deleteComment(id))}
                  onReply={(parentId, body) => page.addComment(body, parentId)}
                />
              ))}
            </ol>
          </section>
        </div>

        <aside className="flex flex-col gap-4 lg:sticky lg:top-6">
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Where is it</h3>
            <IdeaStatusTimeline timeline={idea.timeline} />
          </div>
          <Voters voters={page.voters.data ?? []} />
          {idea.productName && (
            <Card>
              <CardContent className="flex justify-between py-4 text-sm">
                <span className="text-muted-foreground">Product</span>
                <span>{idea.productName}</span>
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
    </>
  );
}
