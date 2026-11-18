/**
 * TEST CONSUMER page service (hand tests only): calls this app's own
 * `/api/dev/lead-capture/*` routes, which hold the key server-side.
 */
import type { WizardSource } from '@/types/lead-capture-wizard';
import type { LeadBody } from '@/types/lead-capture-sources';

export interface TestConsumerSnapshot {
  sources: WizardSource[];
  leads: LeadBody[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, cache: 'no-store' });
  const body = (await res.json().catch(() => ({}))) as T & { error?: { message?: string } };
  if (!res.ok) throw new Error(body.error?.message ?? `Request failed (${res.status}).`);
  return body;
}

export const leadCaptureTestConsumerService = {
  connectUrl: async (sourceId?: string) =>
    (
      await call<{ url: string }>('/api/dev/lead-capture/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceId: sourceId ?? null }),
      })
    ).url,
  snapshot: () => call<TestConsumerSnapshot>('/api/dev/lead-capture/leads'),
};
