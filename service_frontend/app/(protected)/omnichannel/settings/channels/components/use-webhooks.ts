'use client';

import { useCallback, useState } from 'react';
import { whatsappWebhookService } from '@/services/whatsapp-webhook-service';
import type {
  WebhookEndpointInput,
  WebhookEndpointPatch,
  WebhookCreateResult,
  WebhookSecretResult,
} from '@/types/whatsapp-webhook';

export interface UseWebhooksResult {
  /** True while a create/update/rotate request is in flight. */
  saving: boolean;
  /** Register a new endpoint; resolves with the one-time signing secret. */
  create: (input: WebhookEndpointInput) => Promise<WebhookCreateResult>;
  /** Update an endpoint's name / url / events. */
  update: (endpointId: string, patch: WebhookEndpointPatch) => Promise<void>;
  /** Rotate an endpoint's signing secret; resolves with the fresh secret. */
  rotate: (endpointId: string) => Promise<WebhookSecretResult>;
}

/**
 * Create / update / rotate operations for a channel's consumer webhooks
 * (UI → hook → service). Enable / disable / delete / list live in the list
 * config's action registry / fetcher, so the dialogs stay pure UI components
 * that never touch the service directly.
 */
export function useWebhooks(channelId: string): UseWebhooksResult {
  const [saving, setSaving] = useState(false);

  const create = useCallback(
    async (input: WebhookEndpointInput) => {
      setSaving(true);
      try {
        return await whatsappWebhookService.create(channelId, input);
      } finally {
        setSaving(false);
      }
    },
    [channelId],
  );

  const update = useCallback(async (endpointId: string, patch: WebhookEndpointPatch) => {
    setSaving(true);
    try {
      await whatsappWebhookService.update(endpointId, patch);
    } finally {
      setSaving(false);
    }
  }, []);

  const rotate = useCallback(async (endpointId: string) => {
    setSaving(true);
    try {
      return await whatsappWebhookService.rotate(endpointId);
    } finally {
      setSaving(false);
    }
  }, []);

  return { saving, create, update, rotate };
}
