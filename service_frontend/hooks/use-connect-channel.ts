'use client';

import { useCallback, useState } from 'react';
import type {
  Channel,
  EmbeddedSignupResult,
  ManualConnectInput,
  MockWabaOption,
} from '@/types/omnichannel';
import { onboardingService } from '@/services/onboarding-service';

/**
 * Embedded Signup connect flow - the wizard state machine (plan 04 §5.2).
 *
 *   idle ──start()──▶ selecting ──authorize(opt)──▶ exchanging ──▶ connected
 *     ▲                  │                              │
 *     └──── cancel() ────┘                              └──▶ failed ──reset()──▶ idle
 *
 * Phase A: `start()` opens the simulated Meta popup (the wizard renders it) and
 * `authorize()` receives the picked number. Phase B: `start()` launches the real
 * Meta JS SDK and feeds its result straight into `authorize()`; the rest is
 * unchanged (the backend exchange happens in `onboardingService.completeOnboarding`).
 */
export type ConnectState = 'idle' | 'selecting' | 'exchanging' | 'connected' | 'failed';

export interface UseConnectChannelResult {
  state: ConnectState;
  channel: Channel | null;
  error: string | null;
  /** Begin the flow (open the signup popup). */
  start: () => void;
  /** Abandon the popup before authorizing. */
  cancel: () => void;
  /** Authorize a picked mock number → exchange + provision (simulated popup). */
  authorize: (option: MockWabaOption) => Promise<void>;
  /** Provision from a full Embedded Signup result (real Meta SDK path). */
  completeWithResult: (result: EmbeddedSignupResult) => Promise<void>;
  /** Provision via the manual token-paste path (validation escape hatch). */
  connectManual: (input: ManualConnectInput) => Promise<void>;
  /** Mark the flow as exchanging (e.g. while the real popup is open). */
  setExchanging: () => void;
  /** Surface a failure (e.g. real popup cancelled/errored). */
  fail: (message: string) => void;
  /** Return to idle (after success or failure). */
  reset: () => void;
}

export function useConnectChannel(workspaceId: string): UseConnectChannelResult {
  const [state, setState] = useState<ConnectState>('idle');
  const [channel, setChannel] = useState<Channel | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return {
    state,
    channel,
    error,
    start,
    cancel,
    authorize,
    completeWithResult,
    connectManual,
    setExchanging,
    fail,
    reset,
  };
}
