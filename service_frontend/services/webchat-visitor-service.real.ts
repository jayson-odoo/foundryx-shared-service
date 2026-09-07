/**
 * Real web chat VISITOR service - talks to the public FastAPI surface
 * (plan 34 / A7b §5.2), bound at the trio's one export since S6
 * (AC-WEB-63).
 *
 * `publicFetch` (no session, no Bearer, no sign-out-on-401 - there is no
 * session to end) is the base; the visitor's own Bearer - minted by the
 * LOADER and handed to the panel over postMessage (BL-SS-183) - is attached
 * by hand on every call (there is no cookie anywhere, D-A7B-4).
 */
import { publicFetch } from '@/lib/api-client';
import type { VisitorMessage, VisitorMessagesPage } from '@/types/omnichannel';
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
