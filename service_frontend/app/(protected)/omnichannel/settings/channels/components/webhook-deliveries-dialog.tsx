'use client';

import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';
import { WEBHOOK_DELIVERY_STATUS_REGISTRY, eventLabel } from './webhook-status';
import { useWebhookDeliveries } from './use-webhook-deliveries';

export interface WebhookDeliveriesDialogProps {
  /** The endpoint whose deliveries to show, or null while closed. */
  endpoint: WebhookEndpoint | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Read-only recent delivery log for one endpoint. Reflows to stacked cards on
 * mobile and a header-aligned grid on wider screens.
 */
export function WebhookDeliveriesDialog({ endpoint, onOpenChange }: WebhookDeliveriesDialogProps) {
  const { formatDateTime } = useDatetime();
  const { deliveries, loading, error } = useWebhookDeliveries(endpoint?.id ?? null);

  return (
    <Dialog open={endpoint !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Deliveries - {endpoint?.name}</DialogTitle>
        </DialogHeader>
        <DialogBody className="max-h-[60vh] overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading deliveries…
            </div>
          ) : error ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              Could not load deliveries.
            </p>
          ) : deliveries.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">No deliveries yet.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {deliveries.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-col gap-2 rounded-lg border border-border p-3 sm:flex-row sm:items-start sm:justify-between"
                >
                  <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{eventLabel(d.eventType)}</span>
                      <StatusBadge
                        status={d.status}
                        registry={WEBHOOK_DELIVERY_STATUS_REGISTRY}
                        size="sm"
                      />
                    </div>
                    {d.error && (
                      <ClampedText
                        text={d.error}
                        lines={2}
                        className="text-xs text-destructive"
                      />
                    )}
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(d.createdAt)}
                    </span>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground sm:flex-col sm:items-end sm:gap-y-0.5 sm:text-right">
                    <span>
                      {d.attemptCount} {d.attemptCount === 1 ? 'attempt' : 'attempts'}
                    </span>
                    <span>{d.responseStatus !== null ? `HTTP ${d.responseStatus}` : '-'}</span>
                    <span>{d.responseMs !== null ? `${d.responseMs} ms` : '-'}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
