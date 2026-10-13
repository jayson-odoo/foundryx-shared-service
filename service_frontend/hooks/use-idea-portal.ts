'use client';

/**
 * Idea portal hooks (lane IDEA-PORTAL): the session bootstrap + data reads +
 * idea-page actions. UI → these hooks → `ideaPortalService` → api-client.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useSession } from 'next-auth/react';
import { ApiError } from '@/lib/api-client';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import { ideaPortalService } from '@/services/idea-portal-service';
import type {
  PortalActivity,
  PortalCard,
  PortalChangelogItem,
  PortalComment,
  PortalIdea,
  PortalIdeaInput,
  PortalList,
  PortalListQuery,
  PortalPrincipal,
  PortalProduct,
  PortalRoadmap,
  PortalVote,
  PortalVoter,
} from '@/types/idea-portal';

// ── runtime (portal vs Sorento iframe) ─────────────────────────────────────────

export interface IdeaPortalPaths {
  roadmap: string;
  feedback: string;
  changelog: string;
  idea: (id: string) => string;
}

export interface IdeaPortalRuntime {
  mode: 'portal' | 'embed';
  paths: IdeaPortalPaths;
  principal: PortalPrincipal;
  signOut: () => void;
}

export const PORTAL_PATHS: IdeaPortalPaths = {
  roadmap: '/portal/ideas',
  feedback: '/portal/ideas/feedback',
  changelog: '/portal/ideas/changelog',
  idea: (id) => `/portal/ideas/${encodeURIComponent(id)}`,
};

export const EMBED_PORTAL_PATHS: IdeaPortalPaths = {
  roadmap: '/embed/ideas/portal',
  feedback: '/embed/ideas/portal/feedback',
  changelog: '/embed/ideas/portal/changelog',
  idea: (id) => `/embed/ideas/portal/${encodeURIComponent(id)}`,
};

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

/** Shared-service portal: an existing portal token, else a staff login
 * exchange, else the sign-in screen. */
export function usePortalSession(): UsePortalSession {
  const { status: authStatus } = useSession();
  const [status, setStatus] = useState<PortalSessionStatus>('loading');
  const [principal, setPrincipal] = useState<PortalPrincipal | null>(null);

  useEffect(() => {
    if (authStatus === 'loading') return;
    let cancelled = false;
    (async () => {
      if (ideaPortalAuth.get()) {
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
      if (authStatus === 'authenticated') {
        try {
          const s = await ideaPortalService.staffSession();
          if (cancelled) return;
          ideaPortalAuth.set(s.token);
          setPrincipal(s.principal);
          setStatus('ready');
          return;
        } catch {
          // no ideas access for this staff user - show sign-in
        }
      }
      if (!cancelled) setStatus('signin');
    })();
    return () => {
      cancelled = true;
    };
  }, [authStatus]);

  const signOut = useCallback(() => {
    ideaPortalAuth.set(null);
    setPrincipal(null);
    setStatus('signin');
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

  return { status, principal, signOut: () => ideaPortalAuth.set(null) };
}

// ── chatbot-link sign-in (Q1 b) ───────────────────────────────────────────────

export interface UseLinkSignIn {
  submitting: boolean;
  error: string | null;
  confirm: (last4: string) => Promise<string | null>;
}

export function useLinkSignIn(token: string): UseLinkSignIn {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = useCallback(
    async (last4: string): Promise<string | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const s = await ideaPortalService.linkSession(token, last4);
        ideaPortalAuth.set(s.token);
        return s.ideaId ?? null;
      } catch (err) {
        if (err instanceof ApiError && err.status === 429) {
          setError('Too many attempts. Try again later.');
        } else {
          setError('That number does not match this link.');
        }
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [token],
  );
  return { submitting, error, confirm };
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
  addComment: (body: string, parentId?: string | null) => Promise<void>;
  deleteComment: (commentId: string) => Promise<void>;
  likeComment: (commentId: string) => Promise<void>;
  setHidden: (hidden: boolean) => Promise<void>;
  actionError: string | null;
}

export function usePortalIdeaPage(id: string): UsePortalIdeaPage {
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [actionError, setActionError] = useState<string | null>(null);
  const idea = usePortalQuery(() => ideaPortalService.get(id), [id]);
  // Reads follow the survivor id once the idea resolves (merged child links).
  const resolvedId = idea.data?.id ?? id;
  const voters = usePortalQuery(() => ideaPortalService.voters(resolvedId), [resolvedId]);
  const activity = usePortalQuery(
    () => ideaPortalService.activity(resolvedId, order),
    [resolvedId, order],
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
    (body: string, parentId?: string | null) =>
      run(async () => {
        await ideaPortalService.addComment(resolvedId, body, parentId);
        activity.reload();
      }),
    [run, resolvedId, activity],
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

  return {
    idea,
    voters,
    activity,
    order,
    setOrder,
    vote,
    addComment,
    deleteComment,
    likeComment,
    setHidden,
    actionError,
  };
}

// ── submit ────────────────────────────────────────────────────────────────────

export interface UsePortalSubmit {
  submitting: boolean;
  error: string | null;
  submit: (input: PortalIdeaInput) => Promise<PortalIdea | null>;
}

export function usePortalSubmit(): UsePortalSubmit {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = useCallback(async (input: PortalIdeaInput) => {
    setSubmitting(true);
    setError(null);
    try {
      return await ideaPortalService.submit(input);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit the idea.');
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);
  return { submitting, error, submit };
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
