/**
 * Impersonation service - start / stop / read the current session (plan 03 §13).
 * The backend mirrors the active session in `impersonation_sessions`.
 */
import { apiFetch } from '@/lib/api-client';
import type { ImpersonationSession } from '@/lib/impersonation-store';

export interface ImpersonationService {
  start(targetUserId: string): Promise<ImpersonationSession>;
  stop(): Promise<void>;
  current(): Promise<ImpersonationSession | null>;
}

export const impersonationService: ImpersonationService = {
  start(targetUserId) {
    return apiFetch<ImpersonationSession>('/impersonation/start', {
      method: 'POST',
      body: JSON.stringify({ targetUserId }),
    });
  },
  async stop() {
    await apiFetch<{ ended: boolean }>('/impersonation/stop', { method: 'POST' });
  },
  current() {
    return apiFetch<ImpersonationSession | null>('/impersonation/current');
  },
};
