/**
 * Idea portal service (lane IDEA-PORTAL) - the only place the portal talks to
 * `/portal/ideas/*`. Every data call carries the portal token from
 * `ideaPortalAuth`; a 401 clears it so the portal falls back to sign-in
 * (never signs the staff NextAuth session out - that is a different token).
 */
import { ApiError, apiFetch, publicFetch } from '@/lib/api-client';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import type {
  PortalActivity,
  PortalChangelogItem,
  PortalComment,
  PortalIdea,
  PortalIdeaInput,
  PortalLike,
  PortalList,
  PortalListQuery,
  PortalPrincipal,
  PortalProduct,
  PortalRoadmap,
  PortalSession,
  PortalVote,
  PortalVoter,
} from '@/types/idea-portal';

const BASE = '/portal/ideas';

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = ideaPortalAuth.get();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  try {
    return await publicFetch<T>(`${BASE}${path}`, { ...init, headers });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) ideaPortalAuth.set(null);
    throw err;
  }
}

function json(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body) };
}

function listQuery(q: PortalListQuery): string {
  const p = new URLSearchParams();
  if (q.q) p.set('q', q.q);
  (q.columns ?? []).forEach((c) => p.append('column', c));
  if (q.sort) p.set('sort', q.sort);
  if (q.mine) p.set('mine', 'true');
  if (q.productId) p.set('productId', q.productId);
  if (q.includeClosed) p.set('includeClosed', 'true');
  if (q.page) p.set('page', String(q.page));
  if (q.pageSize) p.set('pageSize', String(q.pageSize));
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const ideaPortalService = {
  /** Staff: exchange the shared-service login (NextAuth bearer) for a portal token. */
  staffSession(): Promise<PortalSession> {
    return apiFetch<PortalSession>(`${BASE}/session/staff`, { method: 'POST' });
  },
  /** Sorento CRM user: exchange the ideation embed token. */
  embedSession(embedToken: string): Promise<PortalSession> {
    return publicFetch<PortalSession>(`${BASE}/session/embed`, json({ token: embedToken }));
  },
  /** WhatsApp contact: chatbot link token + last 4 digits of their number. */
  linkSession(token: string, last4: string): Promise<PortalSession> {
    return publicFetch<PortalSession>(`${BASE}/session/link`, json({ token, last4 }));
  },
  me(): Promise<PortalPrincipal> {
    return call<PortalPrincipal>('/me');
  },
  roadmap(opts: { productId?: string | null; mine?: boolean } = {}): Promise<PortalRoadmap> {
    return call<PortalRoadmap>(`/roadmap${listQuery({ productId: opts.productId, mine: opts.mine })}`);
  },
  list(q: PortalListQuery): Promise<PortalList> {
    return call<PortalList>(listQuery(q));
  },
  changelog(): Promise<{ items: PortalChangelogItem[] }> {
    return call<{ items: PortalChangelogItem[] }>('/changelog');
  },
  products(): Promise<PortalProduct[]> {
    return call<PortalProduct[]>('/products');
  },
  submit(input: PortalIdeaInput): Promise<PortalIdea> {
    return call<PortalIdea>('', json(input));
  },
  get(id: string): Promise<PortalIdea> {
    return call<PortalIdea>(`/${encodeURIComponent(id)}`);
  },
  setHidden(id: string, hidden: boolean): Promise<PortalIdea> {
    return call<PortalIdea>(`/${encodeURIComponent(id)}/hidden`, {
      method: 'PUT',
      body: JSON.stringify({ hidden }),
    });
  },
  vote(id: string): Promise<PortalVote> {
    return call<PortalVote>(`/${encodeURIComponent(id)}/vote`, { method: 'POST' });
  },
  voters(id: string): Promise<PortalVoter[]> {
    return call<PortalVoter[]>(`/${encodeURIComponent(id)}/voters`);
  },
  activity(id: string, order: 'asc' | 'desc' = 'desc'): Promise<PortalActivity[]> {
    return call<PortalActivity[]>(`/${encodeURIComponent(id)}/activity?order=${order}`);
  },
  comments(id: string): Promise<PortalComment[]> {
    return call<PortalComment[]>(`/${encodeURIComponent(id)}/comments`);
  },
  addComment(id: string, body: string, parentId?: string | null): Promise<PortalComment> {
    return call<PortalComment>(
      `/${encodeURIComponent(id)}/comments`,
      json(parentId ? { body, parentId } : { body }),
    );
  },
  deleteComment(id: string, commentId: string): Promise<void> {
    return call<void>(`/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}`, {
      method: 'DELETE',
    });
  },
  likeComment(id: string, commentId: string): Promise<PortalLike> {
    return call<PortalLike>(
      `/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}/like`,
      { method: 'POST' },
    );
  },
};
