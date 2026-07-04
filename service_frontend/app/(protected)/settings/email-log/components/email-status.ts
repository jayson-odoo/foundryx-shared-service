import type { StatusRegistry } from '@/components/platform/status-badge';
import type { EmailOutboxStatus } from '@/types/templates';

export const EMAIL_STATUS_REGISTRY: StatusRegistry<EmailOutboxStatus> = {
  PENDING: { label: 'Pending', tone: 'warning' },
  SENDING: { label: 'Sending', tone: 'info' },
  SENT: { label: 'Sent', tone: 'success' },
  FAILED: { label: 'Failed', tone: 'destructive' },
  CANCELLED: { label: 'Cancelled', tone: 'secondary' },
};

export const EMAIL_LOG_PATH = '/settings/email-log';

export function emailLogDetailPath(id: string): string {
  return `${EMAIL_LOG_PATH}/${id}`;
}

/** Detail href preserving record-nav context (ctx + index). */
export function emailLogDetailHref(
  id: string,
  opts?: { ctx?: string; index?: number },
): string {
  const params = new URLSearchParams();
  if (opts?.ctx) params.set('ctx', opts.ctx);
  if (typeof opts?.index === 'number') params.set('i', String(opts.index));
  const qs = params.toString();
  return qs ? `${emailLogDetailPath(id)}?${qs}` : emailLogDetailPath(id);
}
