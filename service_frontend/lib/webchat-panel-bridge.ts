/**
 * The panel <-> loader postMessage bridge (plan 34 / A7b, amended 2026-09-09
 * for BL-SS-183).
 *
 * The LOADER - vanilla JS running in the customer's own top-level document -
 * mints the visitor session and owns the visitor token (in the HOST page's
 * storage, namespaced per widget key). Only a fetch issued from that
 * document carries the embedding website's `Origin`, which is the value the
 * channel's allowlist is about; a fetch from inside this iframe would always
 * carry the app's own origin, which is why the panel no longer starts
 * sessions at all.
 *
 * So the panel's whole session acquisition is: announce `ready`, then wait
 * for the loader's `session` frame. It validates the SOURCE WINDOW
 * (`event.source === window.parent`) rather than a host origin - a panel
 * cannot pin one, it varies per customer - and the panel document's own
 * `frame-ancestors` CSP is what restricts who may embed it. Nothing the
 * panel posts outward carries a secret, so an unpinned target origin on the
 * way out is safe; the token only ever travels inward, from the loader.
 *
 * A panel opened by direct navigation (no loader, no parent) never receives
 * a frame, never gets a token, and therefore never opens a chat.
 */
import type { WebchatSessionResult } from '@/types/omnichannel';

const LOADER_SOURCE = 'fx-webchat-loader';
const PANEL_SOURCE = 'fx-webchat-panel';

/** Frames the loader sends inward. `session` carries a whole
 *  `WebchatSessionResult`; the rest are open/close commands. */
export type LoaderFrameType = 'session' | 'open' | 'close';
/** Frames the panel sends outward - geometry and lifecycle only. */
export type PanelFrameType = 'ready' | 'resize' | 'opened' | 'closed';

export interface LoaderFrame {
  type: LoaderFrameType;
  payload: unknown;
}

const LOADER_FRAME_TYPES: readonly string[] = ['session', 'open', 'close'];

/** True only when this document is genuinely embedded as a child frame. */
export function isEmbedded(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.parent !== window;
  } catch {
    return true;
  }
}

export function postToLoader(type: PanelFrameType, payload?: Record<string, unknown>): void {
  if (!isEmbedded()) return;
  window.parent.postMessage({ source: PANEL_SOURCE, type, payload: payload ?? {} }, '*');
}

/** Validates the source window and the envelope; returns `null` for anything
 *  that did not come from the embedding loader. */
export function readLoaderFrame(event: MessageEvent): LoaderFrame | null {
  if (typeof window === 'undefined' || !isEmbedded()) return null;
  if (event.source !== window.parent) return null;
  const data = event.data as { source?: unknown; type?: unknown; payload?: unknown } | null;
  if (!data || data.source !== LOADER_SOURCE) return null;
  if (typeof data.type !== 'string' || !LOADER_FRAME_TYPES.includes(data.type)) return null;
  return { type: data.type as LoaderFrameType, payload: data.payload };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Structural check on a `session` frame's payload - the panel renders from
 *  it and authorizes every later call with its token, so it is never trusted
 *  by shape alone. */
export function sessionFromPayload(payload: unknown): WebchatSessionResult | null {
  if (!isRecord(payload)) return null;
  const { token, visitorId, workspaceId, config, messages, online } = payload;
  if (typeof token !== 'string' || !token) return null;
  if (typeof visitorId !== 'string' || typeof workspaceId !== 'string') return null;
  if (!isRecord(config) || !isRecord(config.appearance) || !isRecord(config.preChat)) return null;
  if (!Array.isArray(messages) || typeof online !== 'boolean') return null;
  return payload as unknown as WebchatSessionResult;
}
