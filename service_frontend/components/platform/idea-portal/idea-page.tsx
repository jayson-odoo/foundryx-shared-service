'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Heart, Reply, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeaPortal, usePortalAttachmentFetch, usePortalIdeaPage, type ShareAction } from '@/hooks/use-idea-portal';
import {
  AttachmentPicker,
  UploadRetryNotice,
  useAttachmentDraft,
  useUploadRetry,
} from '@/components/platform/attachment-picker/attachment-picker';
import { AttachmentThumbs } from '@/components/platform/attachment-preview/attachment-thumbs';
import { IdeaStatusTimeline } from '@/app/(public)/public/feedback/[token]/components/idea-status-timeline';
import { colorToHex } from '@/components/platform/status-badge';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { dateKey } from '@/lib/datetime';
import { navigateTop } from '@/lib/top-navigate';
import { isCommentPostResult, type FailedUpload } from '@/lib/upload-files';
import type { PortalActivity, PortalComment, PortalIdea, PortalVoter } from '@/types/idea-portal';
import { PortalStatusPill } from './portal-status-pill';
import { PortalLoading, PortalMessage } from './portal-states';
import { UpvoteBox } from './upvote-box';
import { FollowShareBar } from './follow-share-bar';
import { SharePhoneDialog } from './share-phone-dialog';
import { formatFeedbackNumber } from '@/lib/feedback-number';

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
  onRetry,
  placeholder,
  submitLabel,
  autoFocus,
}: {
  onSubmit: (body: string, files: File[]) => Promise<unknown>;
  onRetry: (commentId: string, files: File[]) => Promise<FailedUpload[]>;
  placeholder: string;
  submitLabel: string;
  autoFocus?: boolean;
}) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const draft = useAttachmentDraft();
  const uploads = useUploadRetry(draft, onRetry);
  const trimmed = body.trim();
  const canSend = Boolean(trimmed || draft.files.length > 0) && !busy;
  const send = async () => {
    if (!canSend) return;
    setBusy(true);
    try {
      const sent = draft.files;
      const result = await onSubmit(trimmed, sent);
      // Only what was sent leaves the box; anything typed or added meanwhile stays.
      setBody((current) => (current.trim() === trimmed ? '' : current));
      uploads.track(result, sent);
    } catch {
      // the hook surfaces the error
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2" {...draft.wrapperProps}>
      <Textarea
        rows={3}
        value={body}
        maxLength={MAX_COMMENT}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => setBody(e.target.value)}
      />
      {uploads.pending ? (
        <UploadRetryNotice
          failed={uploads.pending.failed}
          busy={uploads.busy}
          onRetry={() => void uploads.retryNow()}
          onRemove={uploads.removeFailed}
        />
      ) : (
        <div className="flex items-start justify-between gap-2">
          <AttachmentPicker draft={draft} />
          <Button size="sm" disabled={!canSend} onClick={send}>
            {submitLabel}
          </Button>
        </div>
      )}
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
  const { formatDmyDateTime: formatDateTime } = useDatetime();
  const fetchContent = usePortalAttachmentFetch();
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
        {c.body && <p className="mt-1 break-words whitespace-pre-wrap">{c.body}</p>}
        <AttachmentThumbs attachments={c.attachments ?? []} fetchContent={fetchContent} className="mt-2" />
        <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
          <button
            type="button"
            aria-pressed={c.likedByMe}
            aria-label={c.likedByMe ? 'Unlike' : 'Like'}
            onClick={() => onLike(c.id)}
            className={cn(PRESSED_CLASS, 'inline-flex items-center gap-1', c.likedByMe ? 'text-primary' : 'hover:text-foreground')}
          >
            <Heart className="size-3.5" aria-hidden />
            {c.likeCount}
          </button>
          {onReply && (
            <button type="button" onClick={onReply} className={cn(PRESSED_CLASS, 'inline-flex items-center gap-1 hover:text-foreground')}>
              <Reply className="size-3.5" aria-hidden />
              Reply
            </button>
          )}
          {c.canDelete && (
            <button
              type="button"
              aria-label="Delete comment"
              onClick={() => onDelete(c.id)}
              className={cn(PRESSED_CLASS, 'inline-flex items-center gap-1 hover:text-destructive')}
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
  onRetry,
}: {
  e: PortalActivity;
  onLike: (id: string) => void;
  onDelete: (id: string) => void;
  onReply: (parentId: string, body: string, files: File[]) => Promise<unknown>;
  onRetry: (commentId: string, files: File[]) => Promise<FailedUpload[]>;
}) {
  const { formatDmyDateTime: formatDateTime } = useDatetime();
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
                onRetry={onRetry}
                onSubmit={async (body, files) => {
                  const result = await onReply(top.id, body, files);
                  // Stay open while some files still need a retry.
                  if (!(isCommentPostResult(result) && result.failed.length > 0)) setReplying(false);
                  return result;
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
  const when = formatDateTime(e.at);
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
        <b>Feedback submitted</b>
        {e.by ? ` by ${e.by}` : ''}
        {e.source === 'whatsapp' ? ' over WhatsApp' : ''}
      </>
    );
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

/** A feed row: one backend event, or consecutive upvotes on the same LOCAL day
 * folded into one "X and N others upvoted" line. */
export type FeedRow =
  | { kind: 'event'; event: PortalActivity }
  | { kind: 'upvotes'; at: string; names: string[]; count: number };

export function groupFeed(events: PortalActivity[], timeZone: string): FeedRow[] {
  const rows: FeedRow[] = [];
  let groupDay: string | null = null;
  for (const e of events) {
    if (e.kind === 'upvote') {
      const day = dateKey(e.at, { timeZone });
      const last = rows[rows.length - 1];
      if (last && last.kind === 'upvotes' && groupDay === day) {
        last.count += 1;
        if (e.by && !last.names.includes(e.by)) last.names.push(e.by);
        continue;
      }
      groupDay = day;
      rows.push({ kind: 'upvotes', at: e.at, names: e.by ? [e.by] : [], count: 1 });
      continue;
    }
    groupDay = null;
    rows.push({ kind: 'event', event: e });
  }
  return rows;
}

function UpvoteRow({ row }: { row: Extract<FeedRow, { kind: 'upvotes' }> }) {
  const { formatDmyDate: formatDate } = useDatetime();
  const named = row.names.slice(0, 3);
  const others = row.count - named.length;
  return (
    <li className="flex gap-3" data-kind="upvotes">
      <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ backgroundColor: colorToHex('gray') }} aria-hidden />
      <div>
        <div>
          <b>{named.length ? named.join(', ') : `${row.count} ${row.count === 1 ? 'person' : 'people'}`}</b>
          {named.length > 0 && others > 0 ? ` and ${others} ${others === 1 ? 'other' : 'others'}` : ''} upvoted
        </div>
        <div className="text-xs text-muted-foreground">{formatDate(row.at)}</div>
      </div>
    </li>
  );
}

function Fields({ idea }: { idea: PortalIdea }) {
  const fetchContent = usePortalAttachmentFetch();
  const files = idea.attachments ?? [];
  const useCases = (idea.useCases ?? []).filter((u) => u.trim());
  const rows: { label: string; text?: string | null; list?: string[] }[] = [
    { label: 'Business problem', text: idea.problem },
    { label: 'Desired outcome', text: idea.desiredOutcome },
    { label: 'Use cases', list: useCases },
    { label: 'Current workaround', text: idea.currentWorkaround },
  ];
  const shown = rows.filter((r) => (r.list ? r.list.length > 0 : Boolean(r.text && r.text.trim())));
  if (shown.length === 0 && files.length === 0) return null;
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
                    {r.list.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                ) : (
                  r.text
                )}
              </dd>
            </div>
          ))}
        </dl>
        <AttachmentThumbs attachments={files} fetchContent={fetchContent} className={shown.length > 0 ? 'mt-4' : undefined} />
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
  const { mode, paths, principal, shareToken } = useIdeaPortal();
  const back = mode === 'link' ? { href: paths.feedback, label: 'Feedback' } : { href: paths.roadmap, label: 'Roadmap' };
  const { formatDmyDate: formatDate, timeZone } = useDatetime();
  const shareView = mode === 'share' && Boolean(shareToken);
  const page = usePortalIdeaPage(ideaId, shareView ? shareToken : null);
  const idea = page.idea.data;
  // Lane FEEDBACK-SUBSCRIBE: on a share link every action asks for the phone.
  const [phoneAction, setPhoneAction] = useState<ShareAction | null>(null);
  const [followBusy, setFollowBusy] = useState(false);

  if (page.idea.loading && !idea) return <PortalLoading />;
  if (page.idea.notFound) return <PortalMessage text="This feedback isn’t available." />;
  if (!idea) return <PortalMessage text="This feedback could not be loaded." />;

  const onAction = (p: Promise<void>) => p.catch(() => toast.error(page.actionError ?? 'Something went wrong.'));
  const ask = (action: ShareAction) => () => setPhoneAction(action);
  const askAsync = (action: ShareAction) => () => {
    setPhoneAction(action);
    return Promise.resolve();
  };
  const toggleFollow = () => {
    setFollowBusy(true);
    onAction(page.toggleFollow()).finally(() => setFollowBusy(false));
  };

  return (
    <>
      {!shareView && (
        <Link href={back.href} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" aria-hidden />
          {back.label}
        </Link>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="flex min-w-0 flex-col gap-5">
          <div className="flex gap-4" data-testid="portal-idea-hero">
            <UpvoteBox
              size="lg"
              count={idea.upvotes}
              voted={idea.myVote}
              onVote={shareView ? ask('upvote') : () => onAction(page.vote())}
            />
            <div className="min-w-0">
              {idea.ideaNumber && <p className="text-sm font-medium text-muted-foreground">{formatFeedbackNumber(idea.ideaNumber)}</p>}
              <div role="heading" aria-level={1} className="font-heading text-xl font-semibold break-words sm:text-2xl">
                <ClampedText text={idea.title} lines={2} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                {idea.statusLabel && <PortalStatusPill label={idea.statusLabel} color={idea.statusColor} />}
                {idea.submitterFirstName && <span>Submitted by {idea.submitterFirstName}</span>}
                {idea.submittedAt && <span>{formatDate(idea.submittedAt)}</span>}
                {idea.isMine && (
                  <span className="rounded-full border border-primary px-2 py-0.5 text-xs text-primary">Yours</span>
                )}
              </div>
              <div className="mt-3">
                <FollowShareBar
                  following={Boolean(idea.following)}
                  followerCount={idea.followerCount ?? 0}
                  onFollow={
                    idea.isTest ? null : shareView ? ask('follow') : principal.kind === 'contact' ? toggleFollow : null
                  }
                  onShare={shareView || idea.isTest ? null : page.shareUrl}
                  busy={followBusy}
                />
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
              {shareView ? (
                <Button variant="outline" className="w-full" onClick={ask('comment')}>
                  Leave a comment
                </Button>
              ) : (
                <Composer
                  placeholder="Leave a comment"
                  submitLabel="Comment"
                  onRetry={page.retryCommentUploads}
                  onSubmit={(body, files) => (files.length > 0 ? page.addComment(body, undefined, files) : page.addComment(body))}
                />
              )}
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
              {groupFeed(page.activity.data ?? [], timeZone).map((row, i) =>
                row.kind === 'upvotes' ? (
                  <UpvoteRow key={`upvotes-${row.at}-${i}`} row={row} />
                ) : (
                  <ActivityItem
                    key={`${row.event.kind}-${row.event.comment?.id ?? row.event.at}-${i}`}
                    e={row.event}
                    onLike={shareView ? ask('like') : (id) => onAction(page.likeComment(id))}
                    onDelete={(id) => onAction(page.deleteComment(id))}
                    onRetry={page.retryCommentUploads}
                    onReply={
                      shareView
                        ? askAsync('comment')
                        : (parentId, body, files) =>
                            files.length > 0 ? page.addComment(body, parentId, files) : page.addComment(body, parentId)
                    }
                  />
                ),
              )}
            </ol>
          </section>
        </div>

        <aside className="flex flex-col gap-4 lg:sticky lg:top-6">
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Where is it</h3>
            <IdeaStatusTimeline timeline={idea.timeline} />
          </div>
          {!shareView && <Voters voters={page.voters.data ?? []} />}
          {/* A one-product board never names the product (owner 17 Nov); a share
              link is one product's item, so it does not either. */}
          {idea.productName && !principal.productId && !shareView && (
            <Card>
              <CardContent className="flex justify-between py-4 text-sm">
                <span className="text-muted-foreground">Product</span>
                <span>{idea.productName}</span>
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
      {shareView && shareToken && (
        <SharePhoneDialog
          shareToken={shareToken}
          ideaId={idea.id}
          action={phoneAction}
          onClose={() => setPhoneAction(null)}
          onProven={(boardUrl) => {
            setPhoneAction(null);
            if (boardUrl) navigateTop(boardUrl);
            else page.idea.reload();
          }}
        />
      )}
    </>
  );
}
