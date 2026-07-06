import type { StatusRegistry } from '@/components/platform/status-badge';
import type {
  WebhookStatus,
  WebhookDeliveryStatus,
  WebhookEventType,
} from '@/types/whatsapp-webhook';

/**
 * Consumer-webhook status pills — frontend-only registries (the endpoint /
 * delivery lifecycle is a plain enum on the row, not the status engine).
 * ACTIVE = live/green, DISABLED = muted, AUTO_DISABLED = the pipeline gave up
 * (destructive/red).
 */
export const WEBHOOK_STATUS_REGISTRY: StatusRegistry<WebhookStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  DISABLED: { label: 'Disabled', tone: 'secondary' },
  AUTO_DISABLED: { label: 'Auto-disabled', tone: 'destructive' },
};

export const WEBHOOK_STATUS_OPTIONS = [
  { label: 'Active', value: 'ACTIVE' },
  { label: 'Disabled', value: 'DISABLED' },
  { label: 'Auto-disabled', value: 'AUTO_DISABLED' },
];

/** Delivery-attempt pills — SUCCESS green, PENDING amber, FAILED red. */
export const WEBHOOK_DELIVERY_STATUS_REGISTRY: StatusRegistry<WebhookDeliveryStatus> = {
  SUCCESS: { label: 'Success', tone: 'success' },
  PENDING: { label: 'Pending', tone: 'warning' },
  FAILED: { label: 'Failed', tone: 'destructive' },
};

/** Friendly labels for the three event kinds (shared by pills + the picker). */
export const WEBHOOK_EVENT_LABELS: Record<WebhookEventType, string> = {
  'message.inbound': 'Inbound messages',
  'message.status': 'Delivery receipts',
  'contact.updated': 'Contact updates',
};

/** MultiSelect options for the events picker. */
export const WEBHOOK_EVENT_OPTIONS: { label: string; value: WebhookEventType }[] = [
  { label: WEBHOOK_EVENT_LABELS['message.inbound'], value: 'message.inbound' },
  { label: WEBHOOK_EVENT_LABELS['message.status'], value: 'message.status' },
  { label: WEBHOOK_EVENT_LABELS['contact.updated'], value: 'contact.updated' },
];

/** Human label for one event type (unknown values degrade to the raw key). */
export function eventLabel(value: string): string {
  return WEBHOOK_EVENT_LABELS[value as WebhookEventType] ?? value;
}
