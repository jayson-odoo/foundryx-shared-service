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
/** First retry delay; doubled per consecutive failure up to the cap below. */
const RECONNECT_BASE_DELAY_MS = 3000;
const RECONNECT_MAX_DELAY_MS = 30_000;
/**
 * The server's own "you may not have this socket" code (`ws.py::_authorize`,
 * and since review round 1 also the live re-verification inside the relay
 * loop): a revoked token epoch, a deactivated/trashed channel, a blocked
 * tenant, a wrong workspace. None of those heal by retrying, so retrying is
 * how one admin click ("sign out all visitors") turns every open panel into
 * a 3-second reconnect loop, each handshake costing four backend queries.
 */
const PERMANENT_CLOSE_CODE = 4403;
/**
 * ... and a defence for the case where the close code is NOT delivered (a
 * proxy, or a browser that reports 1006): N consecutive closes that never
 * reached `open` are treated the same way.
 */
const MAX_IMMEDIATE_CLOSES = 5;

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
    let immediateCloses = 0;
    let opened = false;

    /** Exponential with full jitter, capped - a thousand panels dropped by
     *  one backend restart must not reconnect in lockstep. */
    const nextDelay = () => {
      const ceiling = Math.min(
        RECONNECT_MAX_DELAY_MS,
        RECONNECT_BASE_DELAY_MS * 2 ** Math.max(0, immediateCloses - 1),
      );
      return RECONNECT_BASE_DELAY_MS / 2 + Math.random() * (ceiling - RECONNECT_BASE_DELAY_MS / 2);
    };

    const connect = () => {
      if (stopped) return;
      opened = false;
      onStatus?.('connecting');
      socket = new WebSocket(
        wsUrl(`/omnichannel/ws?workspaceId=${encodeURIComponent(workspaceId)}&token=${encodeURIComponent(token)}`),
      );
      socket.onopen = () => {
        opened = true;
        immediateCloses = 0;
        onStatus?.('open');
      };
      socket.onmessage = (e) => {
        try {
          const frame = JSON.parse(e.data as string) as { type?: string; message?: VisitorMessage };
          if (frame.type === 'message.created' && frame.message) onMessage(frame.message);
        } catch {
          // Malformed frame - the poll fallback stays the source of truth.
        }
      };
      socket.onclose = (e) => {
        socket = null;
        onStatus?.('closed');
        if (stopped) return;
        if (!opened) immediateCloses += 1;
        // A REFUSAL is permanent by definition (see PERMANENT_CLOSE_CODE) -
        // stop and let the 4s poll fallback (D-A7B-16) carry the transcript;
        // it re-checks the token on its own next call, so a visitor who
        // starts a fresh session gets a socket again without any retry loop
        // here. A drop after a healthy connection retries from the base
        // delay; repeated instant closes back off and eventually stop.
        if (e?.code === PERMANENT_CLOSE_CODE || immediateCloses >= MAX_IMMEDIATE_CLOSES) return;
        retryTimer = setTimeout(connect, nextDelay());
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
