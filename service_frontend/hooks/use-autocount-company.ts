'use client';

import { useCallback, useEffect, useState } from 'react';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCompanyDetail } from '@/types/autocount';

export interface UseAutocountCompanyResult {
  detail: AutocountCompanyDetail | null;
  isLoading: boolean;
  notFound: boolean;
  reload: () => void;
}

/**
 * One AutoCount company + its per-entity sync config. Components never fetch —
 * this is the hook boundary (`UI → hook → service → api-client`).
 */
export function useAutocountCompany(companyId: string): UseAutocountCompanyResult {
  const [detail, setDetail] = useState<AutocountCompanyDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    autocountService
      .getCompany(companyId)
      .then((row) => {
        if (cancelled) return;
        setDetail(row);
        setNotFound(false);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, reloadKey]);

  return { detail, isLoading, notFound, reload };
}
