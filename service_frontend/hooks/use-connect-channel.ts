'use client';

import { useCallback, useState } from 'react';
import type {
  Channel,
  ChannelType,
  EmbeddedSignupResult,
  ManualConnectInput,
  MetaPageOption,
  MockWabaOption,
} from '@/types/omnichannel';
import { onboardingService } from '@/services/onboarding-service';

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
 *   `selecting` for ALL three types - `authorizeMockMeta` plays the role
 *   `authorize()` plays for WhatsApp (the picked page/account IS both the
 *   auth and the selection, exactly like picking a WABA number today).
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
  /** Simulated dialog path - the picked page/account IS the authorization. */
  authorizeMockMeta: (channelType: ChannelType, workspaceId: string, option: MetaPageOption) => Promise<void>;
}

export function useConnectChannel(workspaceId: string): UseConnectChannelResult {
  const [state, setState] = useState<ConnectState>('idle');
  const [channel, setChannel] = useState<Channel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pages, setPages] = useState<MetaPageOption[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);

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
        setError(e instanceof Error ? e.message : 'Could not load your pages. Please try again.');
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
        setError(e instanceof Error ? e.message : 'Connection failed. Please try again.');
        setState('failed');
      }
    },
    [sessionId],
  );

  const authorizeMockMeta = useCallback(
    async (channelType: ChannelType, targetWorkspaceId: string, option: MetaPageOption) => {
      setState('exchanging');
      setError(null);
      try {
        const created = await onboardingService.connectMetaChannel({
          sessionId: 'sandbox',
          workspaceId: targetWorkspaceId,
          channelType: channelType as 'FACEBOOK' | 'INSTAGRAM',
          pageId: option.id,
          igAccountId: option.igAccountId,
        });
        setChannel(created);
        setState('connected');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Connection failed. Please try again.');
        setState('failed');
      }
    },
    [],
  );

  return {
    state,
    channel,
    error,
    pages,
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
    authorizeMockMeta,
  };
}
