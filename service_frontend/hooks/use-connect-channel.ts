'use client';

import { useCallback, useState } from 'react';
import type {
  Channel,
  ChannelType,
  ConnectWebchatInput,
  EmbeddedSignupResult,
  ManualConnectInput,
  MetaPageOption,
  MockWabaOption,
} from '@/types/omnichannel';
import { onboardingService } from '@/services/onboarding-service';
import { webchatService } from '@/services/webchat-service';
import { ApiError } from '@/lib/api-client';

/**
 * Typed 409/400 `detail.reason` -> the human copy the S0 mock always showed
 * (plan 32 / A7a S6). The real `/onboarding/meta/*` routes keep the
 * documented `{reason}` body shape (plan §5.1, pinned by backend tests) -
 * this is the ONE place that turns a reason into prose, so a future reason
 * needs one new row here, never a bare status-line fallback on screen.
 */
const META_CONNECT_REASON_MESSAGES: Record<string, string> = {
  external_account_in_use: 'This page is already connected to another channel.',
  connect_session_expired: 'This connection attempt has expired - start again.',
  connect_session_consumed: 'This connection attempt has already been used - start again.',
};

function connectErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const reason =
      e.detail && typeof e.detail === 'object' && 'reason' in e.detail
        ? String((e.detail as { reason?: unknown }).reason ?? '')
        : '';
    if (reason && META_CONNECT_REASON_MESSAGES[reason]) {
      return META_CONNECT_REASON_MESSAGES[reason];
    }
    return e.message || fallback;
  }
  return e instanceof Error ? e.message : fallback;
}

/**
 * Channel connect wizard state machine (plan 04 §5.2; extended plan 32 / A7a
 * for Messenger + Instagram).
 *
 *   WhatsApp (unchanged):
 *     idle ──start()──▶ selecting ──authorize(opt)──▶ exchanging ──▶ connected
 *       ▲                  │                              │
 *       └──── cancel() ────┘                              └──▶ failed ──reset()──▶ idle
 *
 *   Messenger / Instagram (new states, WhatsApp never enters them):
 *     idle ──startMetaAuth()──▶ authorizing ──authorizeMetaCode(code)──▶ picking-page
 *       ▲         (real popup opened)              (pages exchanged)         │
 *       │                                                                    ▼
 *       └──────────────────────── cancel() ──────────────────── selectMetaPage(page)
 *                                                                            │
 *                                                                            ▼
 *                                                                       exchanging ──▶ connected | failed
 *
 *   Simulated dialog path (no Meta app configured) reuses `start()` →
 *   `selecting` for ALL three Meta-backed types - `authorizeMockMeta` plays
 *   the role `authorize()` plays for WhatsApp (the picked page/account IS
 *   both the auth and the selection, exactly like picking a WABA number
 *   today).
 *
 *   Web chat (plan 34 / A7b, new - no OAuth, no popup at all):
 *     idle ──connectWebchat(input)──▶ exchanging ──▶ connected | failed
 *   Reuses the SAME `exchanging`/`connected`/`failed` states as every other
 *   type so the wizard's success/failure views need no web-chat-specific
 *   fork (D-A7B-1 - a channel TYPE, not a parallel flow).
 */
export type ConnectState =
  | 'idle'
  | 'selecting'
  | 'authorizing'
  | 'picking-page'
  | 'exchanging'
  | 'connected'
  | 'failed';

export interface UseConnectChannelResult {
  state: ConnectState;
  channel: Channel | null;
  error: string | null;
  /** Pages/accounts returned by `authorizeMetaCode` (real path only). */
  pages: MetaPageOption[];
  /**
   * The widget secret returned by `connectWebchat` (AC-WEB-18) - revealed
   * exactly once, here, at the moment of connect; never re-fetchable. `null`
   * for every other channel type and cleared by `reset()`.
   */
  webchatSecret: string | null;
  /** Begin the flow (open the simulated Meta popup - WhatsApp today, also
   *  used by the Messenger/Instagram simulated dialog). */
  start: () => void;
  /** Abandon the flow before it completes (any state). */
  cancel: () => void;
  /** Authorize a picked mock number → exchange + provision (WhatsApp simulated popup). */
  authorize: (option: MockWabaOption) => Promise<void>;
  /** Provision from a full Embedded Signup result (WhatsApp real SDK path). */
  completeWithResult: (result: EmbeddedSignupResult) => Promise<void>;
  /** Provision via the manual token-paste path (WhatsApp validation escape hatch). */
  connectManual: (input: ManualConnectInput) => Promise<void>;
  /** Mark the flow as exchanging (e.g. while the real popup is open). */
  setExchanging: () => void;
  /** Surface a failure (e.g. real popup cancelled/errored). */
  fail: (message: string) => void;
  /** Return to idle (after success or failure). */
  reset: () => void;

  // ---- Messenger / Instagram (plan 32 / A7a) -----------------------------
  /** About to open the real Meta OAuth popup for Messenger/Instagram. */
  startMetaAuth: () => void;
  /** The real popup handed back a code - exchange it for the page list. */
  authorizeMetaCode: (channelType: ChannelType, code: string, redirectUri?: string) => Promise<void>;
  /** Finalize the connect for the page/account picked in the wizard's own step. */
  selectMetaPage: (channelType: ChannelType, workspaceId: string, page: MetaPageOption) => Promise<void>;

  // ---- Web chat (plan 34 / A7b) -------------------------------------------
  /** Provision a `WEBCHAT` channel from the wizard's reduced form (name +
   *  workspace + origins - no OAuth, no page selection). */
  connectWebchat: (input: ConnectWebchatInput) => Promise<void>;
}

export function useConnectChannel(workspaceId: string): UseConnectChannelResult {
  const [state, setState] = useState<ConnectState>('idle');
  const [channel, setChannel] = useState<Channel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pages, setPages] = useState<MetaPageOption[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [webchatSecret, setWebchatSecret] = useState<string | null>(null);

  const start = useCallback(() => {
    setError(null);
    setChannel(null);
    setState('selecting');
  }, []);

  const cancel = useCallback(() => {
    setState('idle');
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setChannel(null);
    setPages([]);
    setSessionId(null);
    setWebchatSecret(null);
    setState('idle');
  }, []);

  const completeWithResult = useCallback(
    async (result: EmbeddedSignupResult) => {
      setState('exchanging');
      setError(null);
      try {
        const created = await onboardingService.completeOnboarding(workspaceId, result);
        setChannel(created);
        setState('connected');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Connection failed. Please try again.');
        setState('failed');
      }
    },
    [workspaceId],
  );

  const authorize = useCallback(
    (option: MockWabaOption) =>
      completeWithResult({
        code: `mock-code-${option.wabaId}`,
        wabaId: option.wabaId,
        phoneNumberId: option.phoneNumberId,
        displayPhoneNumber: option.displayPhoneNumber,
        businessName: option.businessName,
      }),
    [completeWithResult],
  );

  const connectManual = useCallback(async (input: ManualConnectInput) => {
    setState('exchanging');
    setError(null);
    try {
      const created = await onboardingService.manualConnect(input);
      setChannel(created);
      setState('connected');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Manual connect failed.');
      setState('failed');
    }
  }, []);

  const setExchanging = useCallback(() => {
    setError(null);
    setState('exchanging');
  }, []);

  const fail = useCallback((message: string) => {
    setError(message);
    setState('failed');
  }, []);

  const startMetaAuth = useCallback(() => {
    setError(null);
    setChannel(null);
    setPages([]);
    setState('authorizing');
  }, []);

  const authorizeMetaCode = useCallback(
    async (channelType: ChannelType, code: string, redirectUri?: string) => {
      setError(null);
      try {
        const result = await onboardingService.listMetaPages({
          channelType: channelType as 'FACEBOOK' | 'INSTAGRAM',
          code,
          redirectUri,
        });
        setSessionId(result.sessionId);
        setPages(result.pages);
        setState('picking-page');
      } catch (e) {
        setError(connectErrorMessage(e, 'Could not load your pages. Please try again.'));
        setState('failed');
      }
    },
    [],
  );

  const selectMetaPage = useCallback(
    async (channelType: ChannelType, targetWorkspaceId: string, page: MetaPageOption) => {
      if (!sessionId) {
        setError('Your session expired - please reconnect.');
        setState('failed');
        return;
      }
      setState('exchanging');
      setError(null);
      try {
        const created = await onboardingService.connectMetaChannel({
          sessionId,
          workspaceId: targetWorkspaceId,
          channelType: channelType as 'FACEBOOK' | 'INSTAGRAM',
          pageId: page.id,
          igAccountId: page.igAccountId,
        });
        setChannel(created);
        setState('connected');
      } catch (e) {
        setError(connectErrorMessage(e, 'Connection failed. Please try again.'));
        setState('failed');
      }
    },
    [sessionId],
  );

  const connectWebchat = useCallback(async (input: ConnectWebchatInput) => {
    setState('exchanging');
    setError(null);
    try {
      const created = await webchatService.connect(input);
      const { widgetSecret, ...channelFields } = created;
      setChannel(channelFields);
      setWebchatSecret(widgetSecret);
      setState('connected');
    } catch (e) {
      setError(connectErrorMessage(e, 'Could not connect the web chat channel. Please try again.'));
      setState('failed');
    }
  }, []);

  return {
    state,
    channel,
    error,
    pages,
    webchatSecret,
    start,
    cancel,
    authorize,
    completeWithResult,
    connectManual,
    setExchanging,
    fail,
    reset,
    startMetaAuth,
    authorizeMetaCode,
    selectMetaPage,
    connectWebchat,
  };
}
