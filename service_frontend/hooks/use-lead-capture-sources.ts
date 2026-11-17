'use client';

/**
 * Staff side of the hosted wizard (plan 64 L-C): opens it in a popup from a
 * single-use URL and refreshes on its `lead-capture:done` / `closed` message.
 * Only messages from this app's own origin are read.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { leadCaptureSourcesService } from '@/services/lead-capture-sources-service';

export function useLeadCaptureWizardLauncher(onFinished: () => void): (sourceId?: string) => Promise<void> {
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const type = (event.data as { type?: unknown } | null)?.type;
      if (type === 'lead-capture:done' || type === 'lead-capture:closed') finished.current();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  return useCallback(async (sourceId?: string) => {
    // Open first (a popup must start inside the click), then point it at the URL.
    const popup = window.open('', 'lead_capture_wizard', 'popup,width=720,height=860');
    try {
      const url = await leadCaptureSourcesService.wizardUrl(window.location.origin, sourceId);
      if (popup) popup.location.href = url;
      else window.location.href = url;
    } catch (error) {
      popup?.close();
      toast.error(error instanceof Error ? error.message : 'Could not open the setup. Try again.');
    }
  }, []);
}

export interface UseLeadDetail {
  detail: import('@/types/lead-capture-sources').StaffLeadDetail | null;
  error: string | null;
  loading: boolean;
  redelivering: string | null;
  redeliver: (deliveryId: string) => Promise<void>;
  reload: () => void;
}

/** One lead with its delivery attempts (AC-64-53). */
export function useLeadDetail(id: string): UseLeadDetail {
  const [detail, setDetail] = useState<UseLeadDetail['detail']>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [redelivering, setRedelivering] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    leadCaptureSourcesService
      .leadDetail(id)
      .then((d) => live && setDetail(d))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : 'Could not load the lead.'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [id, version]);

  const redeliver = useCallback(async (deliveryId: string) => {
    setRedelivering(deliveryId);
    try {
      await leadCaptureSourcesService.redeliver(deliveryId);
      toast.success('Sent again.');
      setVersion((v) => v + 1);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not send again.');
    } finally {
      setRedelivering(null);
    }
  }, []);

  return { detail, error, loading, redelivering, redeliver, reload: () => setVersion((v) => v + 1) };
}
