'use client';

/**
 * Idea portal hooks (lane IDEA-PORTAL): the session bootstrap + data reads +
 * idea-page actions. UI → these hooks → `ideaPortalService` → api-client.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { signOut as nextAuthSignOut, useSession } from 'next-auth/react';
import { ApiError } from '@/lib/api-client';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import { uploadInOrder, type CommentPostResult, type FailedUpload } from '@/lib/upload-files';
import { ideaPortalService, ideaShareService } from '@/services/idea-portal-service';
import type { IdeaAttachment } from '@/types/ideation';
import type {
  PortalActivity,
  PortalCard,
  PortalChangelogItem,
  PortalComment,
  PortalIdea,
  PortalIdeaInput,
  PortalList,
  PortalListQuery,
  PortalPhoneSession,
  PortalPrincipal,
  PortalProduct,
  PortalRoadmap,
  PortalVote,
  PortalVoter,
} from '@/types/idea-portal';

/** Upload files to the report, or to a comment of it; returns those that failed. */
function uploadFiles(ideaId: string, files: File[], commentId?: string): Promise<FailedUpload[]> {
  return uploadInOrder(files, (file) => ideaPortalService.uploadAttachment(ideaId, file, commentId));
}

/** Fetch an uploaded file's bytes for the thumbnails + preview dialog. The
 * portal route needs the portal token; on a share link the file comes from the
 * token-checked share route instead (no portal token sent or cleared). */
export function usePortalAttachmentFetch(): (attachment: IdeaAttachment) => Promise<Blob> {
  const share = useContext(IdeaPortalContext)?.mode === 'share';
  return useCallback(
    (attachment) =>
      share
        ? ideaShareService.attachmentContent(attachment.contentPath ?? '')
        : ideaPortalService.attachmentContent(attachment.contentPath ?? ''),
    [share],
  );
}

// ── runtime (portal vs Sorento iframe) ─────────────────────────────────────────

export interface IdeaPortalPaths {
  roadmap: string;
  feedback: string;
  changelog: string;
  idea: (id: string) => string;
}

export interface IdeaPortalRuntime {
  /** `link` = a dealer's personal feedback link (no login, no header actions).
   * `share` = one item's read-only share link (lane FEEDBACK-SUBSCRIBE): no
   * tabs, every action goes through the phone step. */
  mode: 'portal' | 'embed' | 'link' | 'share';
  /** `share` mode only: the item's share token. */
  shareToken?: string;
  paths: IdeaPortalPaths;
  principal: PortalPrincipal;
  signOut: () => void;
}

export const PORTAL_PATHS: IdeaPortalPaths = {
  roadmap: '/portal/feedback',
  feedback: '/portal/feedback/list',
  changelog: '/portal/feedback/changelog',
  idea: (id) => `/portal/feedback/${encodeURIComponent(id)}`,
};

export const EMBED_PORTAL_PATHS: IdeaPortalPaths = {
  roadmap: '/embed/feedback/portal',
  feedback: '/embed/feedback/portal/list',
  changelog: '/embed/feedback/portal/changelog',
  idea: (id) => `/embed/feedback/portal/${encodeURIComponent(id)}`,
};

/** A dealer's personal feedback link (lane PUBLIC-IDEAS-BOARD): the board
 * opens on Feedback; the link token is part of every path. */
export function linkPortalPaths(linkToken: string): IdeaPortalPaths {
  // `/public/feedback/board/...`: `/public/feedback/{statusToken}` is the
  // per-item status page (lane FEEDBACK-RENAME), so the board has its own segment.
  const base = `/public/feedback/board/${encodeURIComponent(linkToken)}`;
  return {
    roadmap: `${base}/roadmap`,
    feedback: base,
    changelog: `${base}/changelog`,
    idea: (id) => `${base}/${encodeURIComponent(id)}`,
  };
}

/** The "only mine" toggle label, or null when the viewer has no own items to
 * filter by (staff on the shared-service portal). */
export function mineFilterLabel(principal: PortalPrincipal): string | null {
  if (principal.kind === 'contact') return 'My requests';
  if (principal.kind === 'crm') return 'My feedback';
  return null;
}

export const IdeaPortalContext = createContext<IdeaPortalRuntime | null>(null);

export function useIdeaPortal(): IdeaPortalRuntime {
  const ctx = useContext(IdeaPortalContext);
  if (!ctx) throw new Error('useIdeaPortal must be used inside the idea portal shell');
  return ctx;
}

// ── session bootstrap ─────────────────────────────────────────────────────────

export type PortalSessionStatus = 'loading' | 'ready' | 'signin';

export interface UsePortalSession {
  status: PortalSessionStatus;
  principal: PortalPrincipal | null;
  signOut: () => void;
}

/** Shared-service portal (staff only): needs the staff login. A stored portal
 * token is reused only for the SAME signed-in user; otherwise the login is
 * exchanged for a fresh one. Signed out = the sign-in screen (and the stored
 * token is discarded). */
export function usePortalSession(): UsePortalSession {
  const { status: authStatus, data: authSession } = useSession();
  const userId = authSession?.user?.id ?? null;
  const [status, setStatus] = useState<PortalSessionStatus>('loading');
  const [principal, setPrincipal] = useState<PortalPrincipal | null>(null);

  useEffect(() => {
    if (authStatus === 'loading') return;
    let cancelled = false;
    (async () => {
      if (authStatus !== 'authenticated' || !userId) {
        ideaPortalAuth.set(null);
        setPrincipal(null);
        setStatus('signin');
        return;
      }
      if (ideaPortalAuth.get() && ideaPortalAuth.owner() === userId) {
        try {
          const me = await ideaPortalService.me();
          if (cancelled) return;
          setPrincipal(me);
          setStatus('ready');
          return;
        } catch {
          // stale token - cleared by the service on 401, fall through
        }
      }
      try {
        const s = await ideaPortalService.staffSession();
        if (cancelled) return;
        ideaPortalAuth.set(s.token, userId);
        setPrincipal(s.principal);
        setStatus('ready');
        return;
      } catch {
        // no ideas access for this staff user (or impersonating) - sign-in
        ideaPortalAuth.set(null);
      }
      if (!cancelled) setStatus('signin');
    })();
    return () => {
      cancelled = true;
    };
  }, [authStatus, userId]);

  // The portal sign-in IS the staff login, so signing out of the portal signs
  // out of the staff login too (and lands back on the portal's sign-in).
  const signOut = useCallback(() => {
    ideaPortalAuth.set(null);
    setPrincipal(null);
    setStatus('signin');
    void nextAuthSignOut({ callbackUrl: '/portal/feedback' });
  }, []);

  return { status, principal, signOut };
}

/** Sorento iframe: exchange the already-validated embed token (memory only). */
export function useEmbedPortalSession(embedToken: string | null): UsePortalSession {
  const [status, setStatus] = useState<PortalSessionStatus>('loading');
  const [principal, setPrincipal] = useState<PortalPrincipal | null>(null);

  useEffect(() => {
    ideaPortalAuth.setPersist(false);
    if (!embedToken) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await ideaPortalService.embedSession(embedToken);
        if (cancelled) return;
        ideaPortalAuth.set(s.token);
        setPrincipal(s.principal);
        setStatus('ready');
      } catch {
        if (!cancelled) setStatus('signin');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [embedToken]);

  // A 401 mid-session clears the token (service layer): leave the ready state
  // so the gate shows "not available" instead of a page of inline errors.
  useEffect(
    () =>
      ideaPortalAuth.subscribe((token) => {
        if (token === null) setStatus((s) => (s === 'ready' ? 'signin' : s));
      }),
    [],
  );

  return { status, principal, signOut: () => ideaPortalAuth.set(null) };
}

/** A dealer's personal feedback link: exchange it once per page load. The
 * portal token is kept in memory only (never storage), so a closed tab leaves
 * nothing behind; a cancelled link fails the next request and the gate shows
 * the not-valid message. */
export function useLinkPortalSession(linkToken: string | null): UsePortalSession {
  const [status, setStatus] = useState<PortalSessionStatus>('loading');
  const [principal, setPrincipal] = useState<PortalPrincipal | null>(null);

  useEffect(() => {
    ideaPortalAuth.setPersist(false);
    if (!linkToken) {
      setStatus('signin');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const s = await ideaPortalService.linkSession(linkToken);
        if (cancelled) return;
        ideaPortalAuth.set(s.token);
        setPrincipal(s.principal);
        setStatus('ready');
      } catch {
        if (!cancelled) setStatus('signin');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [linkToken]);

  useEffect(
    () =>
      ideaPortalAuth.subscribe((token) => {
        if (token === null) setStatus((s) => (s === 'ready' ? 'signin' : s));
      }),
    [],
  );

  return { status, principal, signOut: () => ideaPortalAuth.set(null) };
}

// ── generic read ──────────────────────────────────────────────────────────────

export interface PortalQuery<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  reload: () => void;
  setData: (updater: (prev: T | null) => T | null) => void;
}

export function usePortalQuery<T>(fetcher: () => Promise<T>, deps: unknown[]): PortalQuery<T> {
  const [data, setDataState] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNotFound(false);
    fetcherRef
      .current()
      .then((d) => {
        if (!cancelled) setDataState(d);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
        else setError(err instanceof Error ? err.message : 'Something went wrong.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((updater: (prev: T | null) => T | null) => setDataState(updater), []);
  return { data, loading, error, notFound, reload, setData };
}

// ── idea page ─────────────────────────────────────────────────────────────────

export interface UsePortalIdeaPage {
  idea: PortalQuery<PortalIdea>;
  voters: PortalQuery<PortalVoter[]>;
  activity: PortalQuery<PortalActivity[]>;
  order: 'asc' | 'desc';
  setOrder: (o: 'asc' | 'desc') => void;
  vote: () => Promise<void>;
  /** `files` are uploaded to the new comment after it is created (the body may
   * then be empty). */
  addComment: (
    body: string,
    parentId?: string | null,
    files?: File[],
  ) => Promise<CommentPostResult | undefined>;
  /** Retry only the files that failed against a comment that already exists. */
  retryCommentUploads: (commentId: string, files: File[]) => Promise<FailedUpload[]>;
  deleteComment: (commentId: string) => Promise<void>;
  likeComment: (commentId: string) => Promise<void>;
  setHidden: (hidden: boolean) => Promise<void>;
  setNote: (note: string | null) => Promise<void>;
  /** Lane FEEDBACK-SUBSCRIBE: Follow / Following toggle (contact viewer). */
  toggleFollow: () => Promise<void>;
  /** The item's read-only share link. */
  shareUrl: () => Promise<string>;
  actionError: string | null;
}

/** ``shareToken`` set = the read-only share view (lane FEEDBACK-SUBSCRIBE):
 * reads go through the share link; no voters list (names stay off it). */
export function usePortalIdeaPage(id: string, shareToken?: string | null): UsePortalIdeaPage {
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [actionError, setActionError] = useState<string | null>(null);
  const idea = usePortalQuery(
    () => (shareToken ? ideaShareService.get(shareToken) : ideaPortalService.get(id)),
    [id, shareToken],
  );
  // Reads follow the survivor id once the idea resolves (merged child links).
  const resolvedId = idea.data?.id ?? id;
  const voters = usePortalQuery(
    () => (shareToken ? Promise.resolve<PortalVoter[]>([]) : ideaPortalService.voters(resolvedId)),
    [resolvedId, shareToken],
  );
  const activity = usePortalQuery(
    () =>
      shareToken ? ideaShareService.activity(shareToken, order) : ideaPortalService.activity(resolvedId, order),
    [resolvedId, order, shareToken],
  );

  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.status === 429
          ? 'Too many comments. Try again later.'
          : err instanceof Error
            ? err.message
            : 'Something went wrong.',
      );
      throw err;
    }
  }, []);

  const vote = useCallback(
    () =>
      run(async () => {
        const v = await ideaPortalService.vote(resolvedId);
        idea.setData((prev) => (prev ? { ...prev, upvotes: v.upvotes, myVote: v.myVote } : prev));
        voters.reload();
        activity.reload();
      }),
    [run, resolvedId, idea, voters, activity],
  );

  const addComment = useCallback(
    async (body: string, parentId?: string | null, files: File[] = []) => {
      let result: CommentPostResult | undefined;
      await run(async () => {
        const created = await ideaPortalService.addComment(
          resolvedId,
          body,
          parentId,
          files.length > 0 && !body,
        );
        // The comment exists either way: report what did not upload.
        const failed = files.length > 0 ? await uploadFiles(resolvedId, files, created.id) : [];
        result = { commentId: created.id, failed };
        activity.reload();
      });
      return result;
    },
    [run, resolvedId, activity],
  );

  const retryCommentUploads = useCallback(
    async (commentId: string, files: File[]) => {
      const failed = await uploadFiles(resolvedId, files, commentId);
      activity.reload();
      return failed;
    },
    [resolvedId, activity],
  );

  const deleteComment = useCallback(
    (commentId: string) =>
      run(async () => {
        await ideaPortalService.deleteComment(resolvedId, commentId);
        activity.reload();
      }),
    [run, resolvedId, activity],
  );

  const likeComment = useCallback(
    (commentId: string) =>
      run(async () => {
        await ideaPortalService.likeComment(resolvedId, commentId);
        activity.reload();
      }),
    [run, resolvedId, activity],
  );

  const setHidden = useCallback(
    (hidden: boolean) =>
      run(async () => {
        const next = await ideaPortalService.setHidden(resolvedId, hidden);
        idea.setData(() => next);
      }),
    [run, resolvedId, idea],
  );

  const setNote = useCallback(
    (note: string | null) =>
      run(async () => {
        const next = await ideaPortalService.setNote(resolvedId, note);
        idea.setData(() => next);
      }),
    [run, resolvedId, idea],
  );

  const toggleFollow = useCallback(
    () =>
      run(async () => {
        const following = Boolean(idea.data?.following);
        const f = following
          ? await ideaPortalService.unfollow(resolvedId)
          : await ideaPortalService.follow(resolvedId);
        idea.setData((prev) => (prev ? { ...prev, following: f.following, followerCount: f.followerCount } : prev));
      }),
    [run, resolvedId, idea],
  );

  const shareUrl = useCallback(async () => (await ideaPortalService.share(resolvedId)).url, [resolvedId]);

  return {
    idea,
    voters,
    activity,
    order,
    setOrder,
    toggleFollow,
    shareUrl,
    vote,
    addComment,
    retryCommentUploads,
    deleteComment,
    likeComment,
    setHidden,
    setNote,
    actionError,
  };
}

// ── submit ────────────────────────────────────────────────────────────────────

export interface PortalSubmitResult {
  idea: PortalIdea;
  /** Files that failed to upload (the item itself exists). */
  failed: FailedUpload[];
}

export interface UsePortalSubmit {
  submitting: boolean;
  error: string | null;
  /** Create the item, then upload `files` to it one by one. */
  submit: (input: PortalIdeaInput, files?: File[]) => Promise<PortalSubmitResult | null>;
  /** Retry only the given files against an item that already exists. */
  retryUploads: (ideaId: string, files: File[]) => Promise<FailedUpload[]>;
}

export function usePortalSubmit(): UsePortalSubmit {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = useCallback(async (input: PortalIdeaInput, files: File[] = []) => {
    setSubmitting(true);
    setError(null);
    try {
      const idea = await ideaPortalService.submit(input);
      return { idea, failed: await uploadFiles(idea.id, files) };
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit the feedback.');
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);
  const retryUploads = useCallback(async (ideaId: string, files: File[]) => {
    setSubmitting(true);
    try {
      return await uploadFiles(ideaId, files);
    } finally {
      setSubmitting(false);
    }
  }, []);
  return { submitting, error, submit, retryUploads };
}

export type { PortalComment };

// ── list reads + card votes ───────────────────────────────────────────────────

function patchCard(card: PortalCard, v: PortalVote): PortalCard {
  return card.id === v.id ? { ...card, upvotes: v.upvotes, myVote: v.myVote } : card;
}

export function usePortalRoadmap(opts: { mine: boolean; productId: string | null }) {
  const q = usePortalQuery<PortalRoadmap>(
    () => ideaPortalService.roadmap(opts),
    [opts.mine, opts.productId],
  );
  const vote = useCallback(
    async (id: string) => {
      const v = await ideaPortalService.vote(id);
      q.setData((prev) =>
        prev
          ? { columns: prev.columns.map((c) => ({ ...c, ideas: c.ideas.map((i) => patchCard(i, v)) })) }
          : prev,
      );
    },
    [q],
  );
  return { ...q, vote };
}

export function usePortalList(query: PortalListQuery) {
  const key = JSON.stringify(query);
  const q = usePortalQuery<PortalList>(() => ideaPortalService.list(query), [key]);
  const vote = useCallback(
    async (id: string) => {
      const v = await ideaPortalService.vote(id);
      q.setData((prev) => (prev ? { ...prev, items: prev.items.map((i) => patchCard(i, v)) } : prev));
    },
    [q],
  );
  return { ...q, vote };
}

export function usePortalChangelog() {
  return usePortalQuery<{ items: PortalChangelogItem[] }>(() => ideaPortalService.changelog(), []);
}

export function usePortalProducts() {
  return usePortalQuery<PortalProduct[]>(() => ideaPortalService.products(), []);
}

// ── share link phone step (lane FEEDBACK-SUBSCRIBE) ─────────────────────────────

/** What the visitor tapped before the phone step; done for them once proven. */
export type ShareAction = 'follow' | 'upvote' | 'comment' | 'like';

export interface UseSharePhoneStep {
  step: 'phone' | 'code';
  busy: boolean;
  error: string | null;
  sendCode: (phone: string) => Promise<boolean>;
  /** Proves the phone; on success runs ``action`` as the visitor and returns
   * their own board link (null when none). */
  verify: (code: string, action: ShareAction | null, ideaId: string) => Promise<PortalPhoneSession | null>;
  restart: () => void;
  /** Drop a refusal once the visitor edits the number or the code: it was about
   * what they typed before (crew pass 6b78d15b). */
  clearError: () => void;
}

function stepError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      if (err.message) return err.message;
      const minutes = Math.max(1, Math.ceil((err.retryAfterSeconds ?? 900) / 60));
      return `Too many tries. Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`;
    }
    return err.message || 'Something went wrong. Try again.';
  }
  // Same words as the CRM sign-in code step (lane FEEDBACK-SHARE-SS-HOST).
  return 'Unable to reach the server. Please try again.';
}

export function useSharePhoneStep(shareToken: string): UseSharePhoneStep {
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendCode = useCallback(
    async (value: string) => {
      setBusy(true);
      setError(null);
      try {
        await ideaShareService.sendCode(shareToken, value);
        setPhone(value);
        setStep('code');
        return true;
      } catch (err) {
        setError(stepError(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [shareToken],
  );

  const verify = useCallback(
    async (code: string, action: ShareAction | null, ideaId: string) => {
      setBusy(true);
      setError(null);
      try {
        const s = await ideaShareService.verifyCode(shareToken, phone, code);
        ideaPortalAuth.set(s.token);
        // The tap that opened the step, done as the visitor themselves. A
        // failure here still lands them on their own board to retry.
        try {
          if (action === 'follow') await ideaPortalService.follow(ideaId);
          if (action === 'upvote') await ideaPortalService.vote(ideaId);
        } catch {
          /* the board shows the current state */
        }
        return s;
      } catch (err) {
        setError(stepError(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [shareToken, phone],
  );

  const restart = useCallback(() => {
    setStep('phone');
    setError(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { step, busy, error, sendCode, verify, restart, clearError };
}

