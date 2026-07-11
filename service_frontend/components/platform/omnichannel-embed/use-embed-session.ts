'use client';

/**
 * useEmbedSession — the omnichannel embed handshake (sprint-4/11 §4/§5).
 *
 * Lifecycle (contract §5): on mount the widget posts `ready`, then waits for an
 * `init { assertion, theme, colorScheme }` from the parent. It VALIDATES
 * `event.origin` against the assertion's `allowedOrigins` (decoded client-side —
 * server verifies the signature), exchanges the assertion at `/embed/session`
 * for a short-lived access token held IN MEMORY (embedAuthStore), applies the
 * theme, and refreshes silently via `needToken`→`token` at ~80% of the token
 * lifetime. This is the shell's bootstrap — the only place a raw fetch to
 * `/embed/session` lives (it can't go through apiFetch: it MINTS the token
 * apiFetch would attach).
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { embedAuthStore } from '@/lib/embed-auth-store';

import {
  PROTOCOL_VERSION,
  contactIdFromScope,
  decodeAssertionClaims,
  isEnvelope,
  themeToCssVars,
  type ActivityKind,
  type EmbedColorScheme,
  type EmbedEnvelope,
  type EmbedSessionResponse,
  type EmbedTheme,
  type InitPayload,
  type ThemePayload,
  type TokenPayload,
  type WidgetOutboundType,
} from './embed-protocol';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8000';

/** Fraction of the token lifetime after which we proactively request a refresh. */
const REFRESH_AT = 0.8;

export type EmbedStatus = 'awaiting-init' | 'exchanging' | 'ready' | 'error';

export interface UseEmbedSessionResult {
  status: EmbedStatus;
  error: string | null;
  session: EmbedSessionResponse | null;
  /** Resolved from `scope` when `thread:<id>` — else null (inbox scope). */
  contactId: string | null;
  /** Post a coarse activity signal to the parent (no message content). */
  postActivity: (kind: ActivityKind, contactId: string | null) => void;
  /** Post the current content height (inbox mode) to the parent. */
  postResize: (height: number) => void;
}

/** Apply the theme + colorScheme to the embed document (BrandingProvider idiom).
 * The embed page IS its own iframe document, so `documentElement` is the embed
 * root — no host-app pollution; a bare `.dark` class here drives Tailwind's dark
 * variants for the whole widget subtree. */
function applyTheme(theme: EmbedTheme | undefined, colorScheme: EmbedColorScheme | undefined): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const vars = themeToCssVars(theme);
  for (const [cssVar, value] of Object.entries(vars)) root.style.setProperty(cssVar, value);
  if (colorScheme === 'dark') root.classList.add('dark');
  else if (colorScheme === 'light') root.classList.remove('dark');
}

export function useEmbedSession(): UseEmbedSessionResult {
  const [status, setStatus] = useState<EmbedStatus>('awaiting-init');
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<EmbedSessionResponse | null>(null);

  // The validated parent origin (captured from the first accepted `init`) —
  // every subsequent post targets it, every later `theme`/`token` must match it.
  const parentOriginRef = useRef<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const post = useCallback(<T,>(type: WidgetOutboundType, payload: T, targetOrigin: string) => {
    const envelope: EmbedEnvelope<T> = { v: PROTOCOL_VERSION, type, payload };
    window.parent.postMessage(envelope, targetOrigin);
  }, []);

  const scheduleRefresh = useCallback(
    (expiresIn: number) => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      const delay = Math.max(1000, Math.floor(expiresIn * 1000 * REFRESH_AT));
      refreshTimerRef.current = setTimeout(() => {
        const parentOrigin = parentOriginRef.current;
        if (parentOrigin) post('needToken', {}, parentOrigin);
      }, delay);
    },
    [post],
  );

  const exchange = useCallback(
    async (assertion: string, parentOrigin: string) => {
      setStatus((prev) => (prev === 'ready' ? prev : 'exchanging'));
      try {
        const res = await fetch(`${BACKEND_URL}/embed/session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Send the VALIDATED parent origin (captured from the accepted `init`),
          // not the browser Origin header (which is this widget's shared-service
          // origin). The shared service validates THIS against the connection's
          // allowedOrigins (contract §3/§5).
          body: JSON.stringify({ assertion, parentOrigin }),
        });
        if (!res.ok) {
          let message = 'Could not start the conversation.';
          try {
            const body = (await res.json()) as { error?: { message?: string } };
            if (body.error?.message) message = body.error.message;
          } catch {
            /* non-JSON error body */
          }
          throw new Error(message);
        }
        const data = (await res.json()) as EmbedSessionResponse;
        if (!mountedRef.current) return;
        embedAuthStore.set({
          accessToken: data.accessToken,
          workspaceId: data.workspace.id,
          agentId: data.agent.id,
        });
        setSession(data);
        setError(null);
        setStatus('ready');
        scheduleRefresh(data.expiresIn);
      } catch (e: unknown) {
        if (!mountedRef.current) return;
        setError(e instanceof Error ? e.message : 'Could not start the conversation.');
        setStatus('error');
      }
    },
    [scheduleRefresh],
  );

  useEffect(() => {
    mountedRef.current = true;

    const onMessage = (event: MessageEvent) => {
      const data = event.data as unknown;
      if (!isEnvelope(data)) return;
      const envelope = data as EmbedEnvelope<unknown>;

      if (envelope.type === 'init') {
        const payload = envelope.payload as InitPayload;
        if (!payload || typeof payload.assertion !== 'string') return;
        const claims = decodeAssertionClaims(payload.assertion);
        // Reject silently when the origin is not in the assertion's allow-list —
        // NO session exchange, no `'*'` ever accepted (contract §5).
        if (!claims || !claims.allowedOrigins.includes(event.origin)) return;
        // First accepted init wins; ignore repeats once a parent is established.
        if (parentOriginRef.current && parentOriginRef.current !== event.origin) return;
        parentOriginRef.current = event.origin;
        applyTheme(payload.theme, payload.colorScheme);
        void exchange(payload.assertion, event.origin);
        return;
      }

      // `theme` / `token` are only honoured from the established parent origin.
      if (event.origin !== parentOriginRef.current) return;

      if (envelope.type === 'theme') {
        const payload = envelope.payload as ThemePayload;
        applyTheme(payload?.theme, payload?.colorScheme);
      } else if (envelope.type === 'token') {
        const payload = envelope.payload as TokenPayload;
        if (payload && typeof payload.assertion === 'string') {
          const claims = decodeAssertionClaims(payload.assertion);
          // A refreshed assertion must still name this parent origin.
          if (claims && claims.allowedOrigins.includes(event.origin)) {
            void exchange(payload.assertion, event.origin);
          }
        }
      }
    };

    window.addEventListener('message', onMessage);
    // Announce readiness. This is the ONLY `'*'` post: an empty, capability-free
    // ping before the parent origin is known; every later post is origin-pinned
    // and every RECEIVE is origin-validated.
    post('ready', {}, '*');

    return () => {
      mountedRef.current = false;
      window.removeEventListener('message', onMessage);
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      embedAuthStore.clear();
    };
  }, [exchange, post]);

  const postActivity = useCallback(
    (kind: ActivityKind, contactId: string | null) => {
      const parentOrigin = parentOriginRef.current;
      if (parentOrigin) post('activity', { kind, contactId }, parentOrigin);
    },
    [post],
  );

  const postResize = useCallback(
    (height: number) => {
      const parentOrigin = parentOriginRef.current;
      if (parentOrigin) post('resize', { height }, parentOrigin);
    },
    [post],
  );

  const contactId = session ? contactIdFromScope(session.scope) : null;

  return { status, error, session, contactId, postActivity, postResize };
}
