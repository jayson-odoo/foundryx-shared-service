/**
 * Real conversation service (plan 05 Phase B) — api-client + WebSocket.
 *
 * REST goes through apiFetch (Bearer + tenant headers). subscribe() opens a
 * WS to the backend (`/omnichannel/ws?workspaceId=&token=` — browsers can't
 * set headers on WS, so the JWT rides a query param) and auto-reconnects
 * with a small backoff until unsubscribed.
 */
import { getSession } from 'next-auth/react';

import { apiFetch } from '@/lib/api-client';
import type {
  ConversationMessage,
  ConversationSocketEvent,
  ConversationThread,
  QuickReply,
  SendMediaInput,
  SendMessageInput,
  ThreadListQuery,
  ThreadPriority,
  ThreadStatus,
  WhatsAppTemplate,
} from '@/types/omnichannel';

import type { ConversationService } from './conversation-service';

const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

function wsUrl(path: string): string {
  return BASE_URL.replace(/^http/, 'ws') + path;
}

// Interim list cap — the backend defaults to 50; send the max until the inbox
// grows real pagination / infinite-scroll (BL — thread-list pagination).
const THREAD_PAGE_SIZE = 200;

function threadQueryString(query: ThreadListQuery): string {
  const params = new URLSearchParams();
  if (query.workspaceId) params.set('workspaceId', query.workspaceId);
  if (query.assignee && query.assignee !== 'all') params.set('assignee', query.assignee);
  if (query.status && query.status !== 'ALL') params.set('status', query.status);
  if (query.priority && query.priority !== 'ALL') params.set('priority', query.priority);
  if (query.search) params.set('search', query.search);
  params.set('pageSize', String(THREAD_PAGE_SIZE));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

const RECONNECT_DELAY_MS = 3_000;

export const realConversationService: ConversationService = {
  async listThreads(query) {
    const res = await apiFetch<{ data: ConversationThread[] }>(
      `/omnichannel/contacts${threadQueryString(query)}`,
    );
    return res.data;
  },

  async getThread(contactId) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}`);
  },

  async listMessages(contactId) {
    return apiFetch<ConversationMessage[]>(`/omnichannel/contacts/${contactId}/messages`);
  },

  async sendMessage(contactId, input: SendMessageInput) {
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/messages`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async sendMedia(contactId, input: SendMediaInput) {
    // Multipart — apiFetch skips the JSON content-type for a FormData body.
    const form = new FormData();
    form.append('kind', input.kind);
    form.append('file', input.file);
    if (input.caption) form.append('caption', input.caption);
    if (input.replyToMessageId) form.append('reply_to_message_id', input.replyToMessageId);
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/media`, {
      method: 'POST',
      body: form,
    });
  },

  async addInternalNote(contactId, body) {
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/notes`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
  },

  async assign(contactId, userId) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}`, {
      method: 'PATCH',
      body: JSON.stringify({ assignedUserId: userId }),
    });
  },

  async assignToMe(contactId) {
    const session = await getSession();
    const myId = session?.user?.id;
    if (!myId) throw new Error('Not signed in');
    return this.assign(contactId, myId);
  },

  async setStatus(contactId, status: ThreadStatus) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },

  async setPriority(contactId, priority: ThreadPriority) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}`, {
      method: 'PATCH',
      body: JSON.stringify({ priority }),
    });
  },

  async listTemplates(channelId) {
    return apiFetch<WhatsAppTemplate[]>(`/omnichannel/channels/${channelId}/templates`);
  },

  async listQuickReplies(workspaceId) {
    return apiFetch<QuickReply[]>(`/omnichannel/workspaces/${workspaceId}/quick-replies`);
  },

  subscribe(workspaceId, handler: (event: ConversationSocketEvent) => void) {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    // A 4403 can be transient — the JWT expired between getSession() and the
    // handshake. getSession() refreshes the token, so retry a bounded few times
    // (slower cadence) rather than giving up forever on the first auth close.
    let authRetries = 0;
    const MAX_AUTH_RETRIES = 3;

    const connect = async () => {
      const session = await getSession();
      const token = session?.accessToken;
      if (stopped || !token) return;

      socket = new WebSocket(
        wsUrl(`/omnichannel/ws?workspaceId=${encodeURIComponent(workspaceId)}&token=${encodeURIComponent(token)}`),
      );
      socket.onopen = () => {
        authRetries = 0; // a successful connect clears the auth-retry budget
      };
      socket.onmessage = (e) => {
        try {
          handler(JSON.parse(e.data) as ConversationSocketEvent);
        } catch {
          // Malformed frame — drop it; the DB remains the source of truth.
        }
      };
      socket.onclose = (e) => {
        socket = null;
        if (stopped) return;
        if (e.code === 4403) {
          // Genuine permission denial stops after a few tries; a refreshed
          // token on the next attempt recovers an expired-token close.
          if (authRetries++ < MAX_AUTH_RETRIES) {
            retryTimer = setTimeout(() => void connect(), RECONNECT_DELAY_MS * 2);
          }
          return;
        }
        retryTimer = setTimeout(() => void connect(), RECONNECT_DELAY_MS);
      };
    };
    void connect();

    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  },
};
