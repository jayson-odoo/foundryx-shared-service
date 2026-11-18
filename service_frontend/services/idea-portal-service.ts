/**
 * Idea portal service (lane IDEA-PORTAL) - the only place the portal talks to
 * `/portal/ideas/*`. Every data call carries the portal token from
 * `ideaPortalAuth`; a 401 clears it so the portal falls back to sign-in
 * (never signs the staff NextAuth session out - that is a different token).
 */
import { ApiError, apiFetch, publicFetch, publicFetchBlob } from '@/lib/api-client';
import { ideaPortalAuth } from '@/lib/idea-portal-auth';
import type { IdeaAttachment } from '@/types/ideation';
import type {
  PortalActivity,
  PortalChangelogItem,
  PortalComment,
  PortalFollow,
  PortalIdea,
  PortalIdeaInput,
  PortalLike,
  PortalList,
  PortalPhoneSession,
  PortalListQuery,
  PortalPrincipal,
  PortalProduct,
  PortalRoadmap,
  PortalSession,
  PortalShareLink,
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
  /** Dealer: exchange a personal feedback link (no login; lane PUBLIC-IDEAS-BOARD). */
  linkSession(linkToken: string): Promise<PortalSession> {
    return publicFetch<PortalSession>(`${BASE}/session/link`, json({ token: linkToken }));
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
  setNote(id: string, note: string | null): Promise<PortalIdea> {
    return call<PortalIdea>(`/${encodeURIComponent(id)}/note`, {
      method: 'PUT',
      body: JSON.stringify({ note }),
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
  /** `hasAttachments` allows an empty body (the files follow as uploads). */
  addComment(
    id: string,
    body: string,
    parentId?: string | null,
    hasAttachments?: boolean,
  ): Promise<PortalComment> {
    return call<PortalComment>(
      `/${encodeURIComponent(id)}/comments`,
      json({ body, ...(parentId ? { parentId } : {}), ...(hasAttachments ? { hasAttachments: true } : {}) }),
    );
  },
  /** One file onto the report, or onto the caller's own comment with `commentId`. */
  uploadAttachment(id: string, file: File, commentId?: string): Promise<IdeaAttachment> {
    const body = new FormData();
    body.append('file', file);
    if (commentId) body.append('commentId', commentId);
    return call<IdeaAttachment>(`/${encodeURIComponent(id)}/attachments`, { method: 'POST', body });
  },
  /** An uploaded file's bytes (the content route needs the portal token). */
  async attachmentContent(contentPath: string): Promise<Blob> {
    const token = ideaPortalAuth.get();
    const headers = new Headers();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    try {
      return await publicFetchBlob(contentPath, { headers });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) ideaPortalAuth.set(null);
      throw err;
    }
  },
  deleteComment(id: string, commentId: string): Promise<void> {
    return call<void>(`/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}`, {
      method: 'DELETE',
    });
  },
  /** Lane FEEDBACK-SUBSCRIBE: follow / unfollow (a contact on their own link). */
  follow(id: string): Promise<PortalFollow> {
    return call<PortalFollow>(`/${encodeURIComponent(id)}/follow`, { method: 'POST' });
  },
  unfollow(id: string): Promise<PortalFollow> {
    return call<PortalFollow>(`/${encodeURIComponent(id)}/follow`, { method: 'DELETE' });
  },
  /** The item's read-only share link. */
  share(id: string): Promise<PortalShareLink> {
    return call<PortalShareLink>(`/${encodeURIComponent(id)}/share`, { method: 'POST' });
  },
  likeComment(id: string, commentId: string): Promise<PortalLike> {
    return call<PortalLike>(
      `/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}/like`,
      { method: 'POST' },
    );
  },
};

/** One item's read-only share link (lane FEEDBACK-SUBSCRIBE): no session, the
 * share token is the capability; any action goes through the phone step. */
const shared = (token: string, path = '') => `${BASE}/shared/${encodeURIComponent(token)}${path}`;

export const ideaShareService = {
  get(token: string): Promise<PortalIdea> {
    return publicFetch<PortalIdea>(shared(token));
  },
  comments(token: string): Promise<PortalComment[]> {
    return publicFetch<PortalComment[]>(shared(token, '/comments'));
  },
  activity(token: string, order: 'asc' | 'desc' = 'desc'): Promise<PortalActivity[]> {
    return publicFetch<PortalActivity[]>(shared(token, `/activity?order=${order}`));
  },
  /** Step 1: the item's product checks the phone and sends a WhatsApp code. */
  sendCode(token: string, phone: string): Promise<{ sent: boolean }> {
    return publicFetch<{ sent: boolean }>(shared(token, '/phone/send-code'), json({ phone }));
  },
  /** Step 2: the code proves the phone; returns the visitor's own session. */
  verifyCode(token: string, phone: string, code: string): Promise<PortalPhoneSession> {
    return publicFetch<PortalPhoneSession>(shared(token, '/phone/verify'), json({ phone, code }));
  },
};
