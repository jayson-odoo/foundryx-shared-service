'use client';

/**
 * TEST CONSUMER page state (hand tests only): opens the hosted wizard in a
 * popup like a product's "Connect a source" button, listens for its
 * `lead-capture:*` message (this page's own origin only) and shows the
 * key's sources and newest leads.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  leadCaptureTestConsumerService as svc,
  type TestConsumerSnapshot,
} from '@/services/lead-capture-test-consumer-service';

const SETTLE_MS = 7000;

export interface TestConsumerMessage {
  type: string;
  sourceId?: string;
}

export interface UseTestConsumer {
  snapshot: TestConsumerSnapshot | null;
  loading: boolean;
  error: string | null;
  lastMessage: TestConsumerMessage | null;
  connect: (sourceId?: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useLeadCaptureTestConsumer(): UseTestConsumer {
  const [snapshot, setSnapshot] = useState<TestConsumerSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastMessage, setLastMessage] = useState<TestConsumerMessage | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await svc.snapshot();
      if (alive.current) setSnapshot(next);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : 'Could not load.');
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as TestConsumerMessage | null;
      if (data?.type === 'lead-capture:done' || data?.type === 'lead-capture:closed') {
        setLastMessage(data);
        void refresh();
        // The pull API holds back a lead for its first seconds (it may still
        // be committing): read again once the test lead has settled.
        window.setTimeout(() => {
          if (alive.current) void refresh();
        }, SETTLE_MS);
      }
    };
    window.addEventListener('message', onMessage);
    return () => {
      alive.current = false;
      window.removeEventListener('message', onMessage);
    };
  }, [refresh]);

  const connect = useCallback(async (sourceId?: string) => {
    // Open inside the click (popup rules), then point it at the session URL.
    const popup = window.open('', 'lead_capture_wizard', 'popup,width=720,height=860');
    try {
      const url = await svc.connectUrl(sourceId);
      if (popup) popup.location.href = url;
      else window.location.href = url;
    } catch (e) {
      popup?.close();
      setError(e instanceof Error ? e.message : 'Could not open the setup.');
    }
  }, []);

  return { snapshot, loading, error, lastMessage, connect, refresh };
}
