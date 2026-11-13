import type { BroadcastCounts, BroadcastStatus, ConversationSocketEvent } from '@/types/omnichannel';

export interface BroadcastRealtimeUpdate {
  status: BroadcastStatus;
  counts: BroadcastCounts;
}

/**
 * Reconciles one workspace-socket frame against the broadcast currently open
 * on the detail page (plan 29 S4, AC-BRD-13/45) - returns the `{status,
 * counts}` update when `event` is a matching `broadcast.updated` frame, else
 * `null`. A pure function so the detail view's live-refresh wiring is
 * unit-testable without mounting the socket or the form.
 */
export function matchBroadcastUpdate(
  event: ConversationSocketEvent,
  broadcastId: string | null | undefined,
): BroadcastRealtimeUpdate | null {
  if (event.type !== 'broadcast.updated') return null;
  if (!broadcastId || event.broadcastId !== broadcastId) return null;
  return { status: event.status, counts: event.counts };
}
