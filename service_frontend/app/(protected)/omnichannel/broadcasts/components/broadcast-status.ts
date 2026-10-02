import type { StatusRegistry } from '@/components/platform/status-badge';
import type { BroadcastStatus, BroadcastRecipientState } from '@/types/omnichannel';

/**
 * Broadcast lifecycle pills (plan 29, D-A4-3) - the module's own lightweight
 * `statuses` scope, NOT the core status engine (machine-driven, never
 * tenant-edited). Frontend-only registry, mirrors `template-status.ts`.
 */
export const BROADCAST_STATUS_REGISTRY: StatusRegistry<BroadcastStatus> = {
  DRAFT: { label: 'Draft', tone: 'secondary' },
  SCHEDULED: { label: 'Scheduled', tone: 'info' },
  SENDING: { label: 'Sending', tone: 'warning' },
  SENT: { label: 'Sent', tone: 'success' },
  CANCELLED: { label: 'Cancelled', tone: 'secondary' },
  FAILED: { label: 'Failed', tone: 'destructive' },
};

export const BROADCAST_STATUS_SEGMENTS: { id: string; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'SCHEDULED', label: 'Scheduled' },
  { id: 'SENDING', label: 'Sending' },
  { id: 'SENT', label: 'Sent' },
  { id: 'CANCELLED', label: 'Cancelled' },
  { id: 'FAILED', label: 'Failed' },
];

/** Per-recipient delivery pills (recipient state machine, plan §5.6). */
export const RECIPIENT_STATE_REGISTRY: StatusRegistry<BroadcastRecipientState> = {
  queued: { label: 'Queued', tone: 'secondary' },
  sent: { label: 'Sent', tone: 'info' },
  delivered: { label: 'Delivered', tone: 'primary' },
  read: { label: 'Read', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
  skipped: { label: 'Skipped', tone: 'secondary' },
};

export const RECIPIENT_STATE_OPTIONS: { label: string; value: string }[] = [
  { label: 'Queued', value: 'queued' },
  { label: 'Sent', value: 'sent' },
  { label: 'Delivered', value: 'delivered' },
  { label: 'Read', value: 'read' },
  { label: 'Failed', value: 'failed' },
  { label: 'Skipped', value: 'skipped' },
];
