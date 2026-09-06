/**
 * Real conversation service (plan 05 Phase B) - api-client + WebSocket.
 *
 * REST goes through apiFetch (Bearer + tenant headers). subscribe() opens a
 * WS to the backend (`/omnichannel/ws?workspaceId=&token=` - browsers can't
 * set headers on WS, so the JWT rides a query param) and auto-reconnects
 * with a small backoff until unsubscribed.
 */
import { getSession } from 'next-auth/react';

import { apiFetch } from '@/lib/api-client';
import { embedAuthStore } from '@/lib/embed-auth-store';
import type {
  CloseThreadInput,
  ConversationEvent,
  ConversationMessage,
  ConversationSocketEvent,
  ConversationThread,
  LifecycleMove,
  PatchContactInput,
  QuickReply,
  ReactionResult,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  SendTemplateInput,
  ShortcutItem,
  ShortcutRunResult,
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

// Interim list cap - the backend defaults to 50; send the max until the inbox
// grows real pagination / infinite-scroll (BL - thread-list pagination).
const THREAD_PAGE_SIZE = 200;

function threadQueryString(query: ThreadListQuery): string {
  const params = new URLSearchParams();
  if (query.workspaceId) params.set('workspaceId', query.workspaceId);
  if (query.assignee && query.assignee !== 'all') params.set('assignee', query.assignee);
  // Review round 2 (finding 1): when a saved view is active, the backend
  // treats an ABSENT param as "use the view's stored value" and an EXPLICIT
  // `ALL` as "clear it" - so `priority` must always be sent while `viewId`
  // is set, even when the bar reads "All", or the view's stored filter
  // silently wins over an explicit "All" selection (AC-IVE-17). `priority`
  // is always single-value both sides, so there is no ambiguity to track.
  //
  // F2 (round-3 codex triage): `status` can't use the same blanket rule -
  // a saved view's `statuses` is a LIST, and a MULTI-status view collapses
  // to the single-value 'ALL' display (`expandViewFilter`) with NO user
  // action involved. Round 2's fix sent `status=ALL` unconditionally
  // whenever a view was active, which cleared that multi-status view's real
  // server-side filter the instant it was selected. Gate on `statusExplicit`
  // (true only when the FILTER BAR itself set `status`) - an explicit choice
  // (including an explicit "All") still overrides the view; a value that
  // merely reads "All" because of the collapse is omitted so the server
  // applies the view's own stored (possibly multi-status) filter.
  if (query.viewId) {
    if (query.statusExplicit) {
      params.set('status', query.status && query.status !== 'ALL' ? query.status : 'ALL');
    }
    params.set('priority', query.priority && query.priority !== 'ALL' ? query.priority : 'ALL');
  } else {
    if (query.status && query.status !== 'ALL') params.set('status', query.status);
    if (query.priority && query.priority !== 'ALL') params.set('priority', query.priority);
  }
  if (query.search) params.set('search', query.search);
  // Plan 27 (AC-IVE-15/16/17) - server-side filtering + sorting.
  if (query.lifecycleStageIds?.length) params.set('lifecycleStageIds', query.lifecycleStageIds.join(','));
  if (query.tagIds?.length) params.set('tagIds', query.tagIds.join(','));
  if (query.channelIds?.length) params.set('channelIds', query.channelIds.join(','));
  // `unreplied` is a bool, unlike every other param above - `false` is a
  // meaningful EXPLICIT override of a saved view's stored `unreplied: true`
  // (AC-IVE-17), so it must always be sent (a truthy-only check would let a
  // toggled-off switch silently fall back to the view's value since the
  // backend treats "param absent" as "no override").
  if (query.viewId) params.set('unreplied', String(!!query.unreplied));
  else if (query.unreplied) params.set('unreplied', 'true');
  if (query.sort) params.set('sort', query.sort);
  if (query.viewId) params.set('viewId', query.viewId);
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

  async sendTemplate(contactId, input: SendTemplateInput) {
    const payload = {
      messageType: 'TEMPLATE' as const,
      templateId: input.templateId,
      templateVariables: input.templateVariables,
      templateHeaderVariables: input.templateHeaderVariables,
      templateButtonVariables: input.templateButtonVariables,
      replyToMessageId: input.replyToMessageId,
    };
    if (input.headerFile) {
      // Multipart when a media header is attached (apiFetch skips JSON for FormData).
      const form = new FormData();
      form.append('payload', JSON.stringify(payload));
      form.append('file', input.headerFile);
      return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/template`, {
        method: 'POST',
        body: form,
      });
    }
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/template`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async sendMedia(contactId, input: SendMediaInput) {
    // Multipart - apiFetch skips the JSON content-type for a FormData body.
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

  async sendInteractive(contactId, input: SendInteractiveInput) {
    const defn = { ...input.definition, replyToMessageId: input.replyToMessageId };
    if (input.headerFile) {
      // Multipart when a media header is attached (apiFetch skips JSON for FormData).
      const form = new FormData();
      form.append('payload', JSON.stringify(defn));
      form.append('file', input.headerFile);
      return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/interactive`, {
        method: 'POST',
        body: form,
      });
    }
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/interactive`, {
      method: 'POST',
      body: JSON.stringify(defn),
    });
  },

  async sendLocation(contactId, input: SendLocationInput) {
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/location`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async sendContacts(contactId, input: SendContactsInput) {
    return apiFetch<ConversationMessage>(`/omnichannel/contacts/${contactId}/contacts`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async react(contactId, messageId, emoji) {
    return apiFetch<ReactionResult>(
      `/omnichannel/contacts/${contactId}/messages/${messageId}/react`,
      { method: 'POST', body: JSON.stringify({ emoji }) },
    );
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
    // Embed runtime: the actor is the external agent - self-claim to its id
    // (the backend embed principal attributes assignment to the external agent).
    const embed = embedAuthStore.getState();
    if (embed) return this.assign(contactId, embed.agentId);
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

  // Plan 25 - not yet backed (routes land in S1-S2); written against the
  // §5.1 contract so the S0->S4 swap is the one-line export change.
  async patchContact(contactId, patch: PatchContactInput) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  async moveLifecycle(contactId, toStatusId) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}/lifecycle`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },

  async lifecycleMoves(contactId) {
    return apiFetch<LifecycleMove[]>(`/omnichannel/contacts/${contactId}/lifecycle-moves`);
  },

  subscribe(workspaceId, handler: (event: ConversationSocketEvent) => void) {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    // A 4403 can be transient - the JWT expired between getSession() and the
    // handshake. getSession() refreshes the token, so retry a bounded few times
    // (slower cadence) rather than giving up forever on the first auth close.
    let authRetries = 0;
    const MAX_AUTH_RETRIES = 3;

    const connect = async () => {
      // Embed runtime authenticates the WS with the in-memory embed access
      // token (read fresh each connect so a refreshed token is picked up on
      // reconnect); otherwise the NextAuth JWT. Browsers can't set WS headers,
      // so it rides the `token` query param either way.
      const embed = embedAuthStore.getState();
      const token = embed?.accessToken ?? (await getSession())?.accessToken;
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
          // Malformed frame - drop it; the DB remains the source of truth.
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

  // -- Plan 27 additions (§5.1) - not yet bound (S0 uses the mock for these
  // four; the routes land S1-S3). Written now so the S4 swap is one line. --
  async closeThread(contactId, input: CloseThreadInput) {
    return apiFetch<ConversationThread>(`/omnichannel/contacts/${contactId}/close`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async listEvents(contactId) {
    const res = await apiFetch<{ data: ConversationEvent[] }>(
      `/omnichannel/contacts/${contactId}/events`,
    );
    return res.data;
  },

  async listShortcuts(contactId) {
    return apiFetch<ShortcutItem[]>(`/omnichannel/contacts/${contactId}/shortcuts`);
  },

  async runShortcut(contactId, workflowId) {
    return apiFetch<ShortcutRunResult>(`/omnichannel/contacts/${contactId}/shortcuts/${workflowId}`, {
      method: 'POST',
    });
  },
};
