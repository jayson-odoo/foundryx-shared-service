'use client';

import { useEffect, useState } from 'react';
import { whatsappWebhookService } from '@/services/whatsapp-webhook-service';
import type { WebhookDelivery } from '@/types/whatsapp-webhook';

export interface UseWebhookDeliveriesResult {
  deliveries: WebhookDelivery[];
  loading: boolean;
  error: boolean;
}

/**
 * Loads an endpoint's recent delivery attempts (UI → hook → service). Refetches
 * whenever `endpointId` changes; a null id (dialog closed) resolves to empty.
 */
export function useWebhookDeliveries(endpointId: string | null): UseWebhookDeliveriesResult {
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!endpointId) {
      setDeliveries([]);
      setError(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(false);
    whatsappWebhookService
      .deliveries(endpointId)
      .then((rows) => active && setDeliveries(rows))
      .catch(() => active && setError(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [endpointId]);

  return { deliveries, loading, error };
}
