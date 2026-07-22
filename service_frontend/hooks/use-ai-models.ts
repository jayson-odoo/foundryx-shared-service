'use client';

import { useEffect, useState } from 'react';
import { aiService } from '@/services/ai-service';
import type { AiModelOption } from '@/types/ai';

export interface UseAiModelsResult {
  models: AiModelOption[];
  isLoading: boolean;
  /** False when the live catalog call failed and the curated static list is
   *  being shown instead — the picker still works either way (AC-BI-05). */
  isLive: boolean;
  message: string | null;
}

/**
 * Model options for the agent form's picker.
 *
 * NEVER throws to the caller: a provider outage degrades to the curated static
 * list (the backend does the fallback and reports `isLive: false`), so the form
 * always renders. Returns [] only while no connection is selected yet.
 */
export function useAiModels(connectionId: string | null | undefined): UseAiModelsResult {
  const [models, setModels] = useState<AiModelOption[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isLive, setIsLive] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!connectionId) {
      setModels([]);
      setMessage(null);
      setIsLive(true);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    aiService
      .listModels(connectionId)
      .then((result) => {
        if (cancelled) return;
        setModels(result.data);
        setIsLive(result.isLive);
        setMessage(result.message);
      })
      .catch(() => {
        // The endpoint itself failed (not just the provider). Keep the form
        // usable rather than blanking it — the pinned model is still valid.
        if (cancelled) return;
        setModels([]);
        setIsLive(false);
        setMessage('Could not load the model list.');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connectionId]);

  return { models, isLoading, isLive, message };
}
