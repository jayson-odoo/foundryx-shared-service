'use client';

import { useEffect, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCallDetail } from '@/types/autocount';

export interface UseCallDetailResult {
  detail: AutocountCallDetail | null;
  isLoading: boolean;
  error: string | null;
}

/** One logged call with its request JSON and response body; idle while `id` is null. */
export function useCallDetail(id: string | null): UseCallDetailResult {
  const [detail, setDetail] = useState<AutocountCallDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setDetail(null);
      setError(null);
      return;
    }
    let active = true;
    setIsLoading(true);
    setError(null);
    autocountService
      .getCall(id)
      .then((next) => {
        if (active) setDetail(next);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : 'Could not load this call.');
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);

  return { detail, isLoading, error };
}
