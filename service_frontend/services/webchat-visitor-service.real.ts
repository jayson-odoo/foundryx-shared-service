/**
 * Real web chat VISITOR service - talks to the public FastAPI surface
 * (plan 34 / A7b §5.2). NOT wired at runtime until slice S6 (AC-WEB-63);
 * `webchat-visitor-service.ts` binds `mockWebchatVisitorService` until then.
 * Written now (and used for S4's own live-verify evidence via a temporary
 * local export flip - see the S4 commit body) so the S6 swap is a one-line
 * export change, no call-site edits.
 *
 * `publicFetch` (no session, no Bearer, no sign-out-on-401 - there is no
 * session to end) is the base; the visitor's own Bearer is attached by hand
 * on every call after `startSession`, exactly as the contract requires
 * (there is no cookie anywhere, D-A7B-4).
 */
import { publicFetch } from '@/lib/api-client';
import type { VisitorMessage, VisitorMessagesPage, WebchatSessionResult } from '@/types/omnichannel';
import type { WebchatVisitorService } from './webchat-visitor-service';

const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';
const RECONNECT_DELAY_MS = 3000;

function wsUrl(path: string): string {
  return BASE_URL.replace(/^http/, 'ws') + path;
}

function isVisitorMessage(value: unknown): value is VisitorMessage {
  return typeof value === 'object' && value !== null && typeof (value as { id?: unknown }).id === 'string';
}

export const realWebchatVisitorService: WebchatVisitorService = {
  startSession(widgetKey, token) {
    return publicFetch<WebchatSessionResult>(
      `/public/omnichannel/webchat/${widgetKey}/session`,
      {
        method: 'POST',
        body: JSON.stringify(token ? { token } : {}),
      },
    );
  },

  async sendMessage(widgetKey, token, input) {
    const result = await publicFetch<Record<string, unknown>>(
      `/public/omnichannel/webchat/${widgetKey}/messages`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify(input),
      },
    );
    return isVisitorMessage(result) ? result : null;
  },

  listMessages(widgetKey, token, after) {
    const params = new URLSearchParams();
    if (after) params.set('after', after);
    const qs = params.toString();
    return publicFetch<VisitorMessagesPage>(
      `/public/omnichannel/webchat/${widgetKey}/messages${qs ? `?${qs}` : ''}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
  },

  subscribe(workspaceId, token, onMessage, onStatus) {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (stopped) return;
      onStatus?.('connecting');
      socket = new WebSocket(
        wsUrl(`/omnichannel/ws?workspaceId=${encodeURIComponent(workspaceId)}&token=${encodeURIComponent(token)}`),
      );
      socket.onopen = () => onStatus?.('open');
      socket.onmessage = (e) => {
        try {
          const frame = JSON.parse(e.data as string) as { type?: string; message?: VisitorMessage };
          if (frame.type === 'message.created' && frame.message) onMessage(frame.message);
        } catch {
          // Malformed frame - the poll fallback stays the source of truth.
        }
      };
      socket.onclose = () => {
        socket = null;
        onStatus?.('closed');
        if (stopped) return;
        // A visitor with no contact yet (never sent a message) is refused at
        // the handshake (4403, S3 D-A7B) - the hook only calls `subscribe`
        // once a contact exists, so any close here is a genuine drop:
        // retry with the same small fixed backoff regardless of code.
        retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
      socket.onerror = () => {
        socket?.close();
      };
    };
    connect();

    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  },
};
