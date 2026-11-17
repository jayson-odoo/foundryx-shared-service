'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { leadCaptureService } from '@/services/lead-capture-service';
import type {
  LeadEvent,
  LeadField,
  LeadFieldList,
  LeadFormQuestions,
  LeadKeyCreated,
  LeadReceiverCreated,
  LeadReceiverItem,
  LeadSourceItem,
} from '@/types/lead-capture';

/**
 * Lead Capture hooks (lane L-D) - the screens' only way to the service layer
 * (UI -> hook -> service -> api-client). Lists read through their ResourceList
 * fetchers; these cover the mutations + the non-list reads.
 */

/** Plain message for a failed call: the backend's `{code, message}` detail, else the error text. */
export function leadCaptureErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { message?: unknown } | undefined;
    if (detail && typeof detail.message === 'string' && detail.message) return detail.message;
    if (err.message) return err.message;
  }
  return fallback;
}

/** Run one async call with a busy flag. */
function useBusy<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async (...args: A): Promise<R> => {
      setBusy(true);
      try {
        return await fn(...args);
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { busy, run };
}

export function useCreateLeadKey(): { creating: boolean; create: (name: string) => Promise<LeadKeyCreated> } {
  const { busy, run } = useBusy(leadCaptureService.createKey);
  return { creating: busy, create: run };
}

export function useCreateLeadReceiver(): {
  creating: boolean;
  create: (url: string, events: LeadEvent[]) => Promise<LeadReceiverCreated>;
} {
  const { busy, run } = useBusy(leadCaptureService.createReceiver);
  return { creating: busy, create: run };
}

export function useSendTestPush(): (receiverId: string) => Promise<void> {
  return leadCaptureService.sendTestPush;
}

export function useRemoveReceivers(): { removing: boolean; remove: (ids: string[]) => Promise<void> } {
  const { busy, run } = useBusy(leadCaptureService.removeReceivers);
  return { removing: busy, remove: run };
}

/** Load state shared by the non-list reads. */
export interface LoadState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useLoad<T>(load: () => Promise<T>, fallback: string): LoadState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    load()
      .then((value) => {
        if (alive) setData(value);
      })
      .catch((err: unknown) => {
        if (alive) setError(leadCaptureErrorMessage(err, fallback));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [load, fallback, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload };
}

/** The receivers as one list (the Delivery page's Push / Pull only state). */
export function useReceivers(): LoadState<LeadReceiverItem[]> {
  return useLoad(leadCaptureService.listReceivers, 'Could not load the receivers.');
}

export function useLeadFields(): LoadState<LeadFieldList> & {
  saving: boolean;
  save: (fields: LeadField[]) => Promise<LeadFieldList>;
} {
  const state = useLoad(leadCaptureService.getFields, 'Could not load the lead fields.');
  const { busy, run } = useBusy(leadCaptureService.saveFields);
  return { ...state, saving: busy, save: run };
}

export function useLeadSources(): LoadState<LeadSourceItem[]> {
  return useLoad(leadCaptureService.listSources, 'Could not load the lead sources.');
}

export function useFormQuestions(sourceId: string, formId: string): LoadState<LeadFormQuestions> {
  const load = useCallback(() => leadCaptureService.formQuestions(sourceId, formId), [sourceId, formId]);
  return useLoad(load, 'Could not load the form questions.');
}

export function useSaveFieldMap(): {
  saving: boolean;
  save: (sourceId: string, formId: string, map: Record<string, string | null>) => Promise<LeadSourceItem>;
} {
  const { busy, run } = useBusy(leadCaptureService.saveFieldMap);
  return { saving: busy, save: run };
}
